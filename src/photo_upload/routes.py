import base64
import datetime
import logging
import os
import socket
import uuid
from io import BytesIO

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
)
from werkzeug.utils import secure_filename

from src import events
from src.events import broker

from ..slideshow import database as slideshow_db
from .auth import generate_upload_url, rate_limit_upload, require_upload_token

# Set up logger
logger = logging.getLogger(__name__)

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pillow_heif

    # Register HEIF opener with PIL
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:
    HEIF_AVAILABLE = False
    logger.warning("pillow-heif not available, HEIC images will not be converted")

try:
    import qrcode

    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

upload_bp = Blueprint("upload", __name__, url_prefix="/upload")


@upload_bp.after_request
def after_request(response):
    """Add CORS headers to all upload responses."""
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add(
        "Access-Control-Allow-Headers", "Content-Type,Authorization,X-Upload-Token"
    )
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "heic", "heif"}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB, per individual photo
THUMBNAIL_SIZE = (300, 300)

# A single upload request may carry several photos (the form posts every
# selected file at once), so the app-wide body limit has to cover a whole
# batch rather than a single file. These constants are the source of truth for
# MAX_CONTENT_LENGTH, which src.main.create_app installs on the Flask app so
# that oversized bodies are rejected by Werkzeug before anything is buffered.
MAX_FILES_PER_REQUEST = 10  # mirrors RateLimiter.upload_limits
MULTIPART_OVERHEAD = 1024 * 1024  # 1MB for part boundaries/headers/token field
MAX_UPLOAD_CONTENT_LENGTH = MAX_FILE_SIZE * MAX_FILES_PER_REQUEST + MULTIPART_OVERHEAD

# Pagination bounds for the photo listing endpoint.
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 100


def allowed_file(filename):
    """Check if the file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_thumbnail(image_path, thumbnail_path):
    """Create a thumbnail for the uploaded image."""
    if not PIL_AVAILABLE:
        logger.warning("PIL not available, skipping thumbnail creation")
        return None

    try:
        with Image.open(image_path) as img:
            # Convert to RGB if needed (handles HEIC/HEIF and RGBA images)
            if img.mode in ["HEIC", "HEIF", "RGBA", "P"]:
                img = img.convert("RGB")

            # Create thumbnail maintaining aspect ratio
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

            # Save as JPEG for consistency
            thumbnail_path = thumbnail_path.rsplit(".", 1)[0] + "_thumb.jpg"
            img.save(thumbnail_path, "JPEG", quality=85, optimize=True)

            return thumbnail_path
    except Exception as e:
        logger.error(f"Failed to create thumbnail for {image_path}: {e}")
        return None


def optimize_image(image_path):
    """Optimize image size and quality for web display."""
    if not PIL_AVAILABLE:
        logger.warning("PIL not available, skipping image optimization")
        return image_path

    try:
        # Check if this is a HEIC/HEIF file by extension
        is_heic = image_path.lower().endswith((".heic", ".heif"))

        if is_heic and not HEIF_AVAILABLE:
            logger.warning(
                f"Cannot process HEIC file {image_path} - pillow-heif not available"
            )
            # Try to remove the file since browsers can't display it
            try:
                os.remove(image_path)
            except OSError:
                pass
            return None

        with Image.open(image_path) as img:
            # Always convert HEIC/HEIF to JPEG for browser compatibility
            if is_heic or img.format in ["HEIC", "HEIF"]:
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")

                # Save as JPEG with a new filename
                new_path = image_path.rsplit(".", 1)[0] + ".jpg"
                img.save(new_path, "JPEG", quality=85, optimize=True)

                # Remove original HEIC/HEIF file
                try:
                    os.remove(image_path)
                    logger.info(f"Converted HEIC to JPEG: {os.path.basename(new_path)}")
                except Exception as e:
                    logger.error(f"Failed to remove original HEIC file: {e}")

                return new_path

            # Optimize existing formats
            elif img.format in ["JPEG", "PNG", "WEBP"]:
                # Resize if too large (max 2000px on longest side)
                max_size = 2000
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                img.save(image_path, img.format, quality=85, optimize=True)

            return image_path

    except Exception as e:
        logger.error(f"Failed to optimize image {image_path}: {e}")
        # If it's a HEIC file that failed, remove it
        if image_path.lower().endswith((".heic", ".heif")):
            try:
                os.remove(image_path)
                logger.info(
                    f"Removed incompatible HEIC file: {os.path.basename(image_path)}"
                )
            except OSError:
                pass
            return None
        return image_path


@upload_bp.route("/")
def upload_page():
    """Render the photo upload page."""
    # Never log request.args here: the upload token is passed as ?token=...
    logger.debug("Photo upload page accessed from %s", request.remote_addr)

    now = datetime.datetime.now()
    from src.config import get_config

    config = get_config()
    family_name = config.get("app.family_name", "Family")

    return render_template(
        "photo_upload.html",
        current_year=now.year,
        current_month=now.month,
        family_name=family_name,
    )


@upload_bp.route("/api/photos", methods=["OPTIONS"])
def upload_photos_preflight():
    """Handle CORS preflight requests."""
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add(
        "Access-Control-Allow-Headers", "Content-Type,Authorization,X-Upload-Token"
    )
    response.headers.add("Access-Control-Allow-Methods", "POST,OPTIONS")
    return response


@upload_bp.route("/api/photos", methods=["POST"])
@require_upload_token
@rate_limit_upload
def upload_photos():
    """Handle photo upload from mobile devices."""
    # SECURITY: never dump request.form here -- the upload token is submitted
    # as a form field, so a full form dump writes the credential to the log.
    if "photos" not in request.files:
        logger.warning("No 'photos' field in request files")
        return jsonify({"error": "No photos provided"}), 400

    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No photos selected"}), 400

    logger.debug(
        "Upload request from %s with %d file(s)", request.remote_addr, len(files)
    )

    uploaded_files = []
    errors = []

    photos_dir = os.path.join(current_app.static_folder, "photos")
    thumbnails_dir = os.path.join(photos_dir, "thumbnails")
    os.makedirs(photos_dir, exist_ok=True)
    os.makedirs(thumbnails_dir, exist_ok=True)

    for file in files:
        if file.filename == "":
            continue

        if not allowed_file(file.filename):
            errors.append(
                f"Invalid file type: {file.filename}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
            continue

        # Check file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)  # Reset file pointer

        if file_size > MAX_FILE_SIZE:
            errors.append(f"File too large: {file.filename}. Max size: 16MB")
            continue

        # Generate unique filename to prevent conflicts
        filename = secure_filename(file.filename)
        name, ext = os.path.splitext(filename)
        unique_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"

        filepath = os.path.join(photos_dir, unique_filename)

        try:
            # Save the uploaded file
            file.save(filepath)
            logger.debug("Saved uploaded file: %s", unique_filename)

            # Optimize the image
            optimized_path = optimize_image(filepath)

            # Check if optimization failed (e.g., incompatible HEIC)
            if optimized_path is None:
                errors.append(
                    f"Unable to process {file.filename} - format not supported"
                )
                continue

            final_filename = os.path.basename(optimized_path)

            # Create thumbnail
            thumbnail_path = os.path.join(thumbnails_dir, final_filename)
            create_thumbnail(optimized_path, thumbnail_path)

            uploaded_files.append(
                {
                    "filename": final_filename,
                    "original_name": file.filename,
                    "size": os.path.getsize(optimized_path),
                }
            )

        except Exception as e:
            logger.error(f"Failed to process {filename}: {e}")
            errors.append(f"Failed to save {filename}: {str(e)}")
            # Clean up partial file if it exists
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass

    # Sync database with new photos
    try:
        slideshow_db.sync_photos(current_app.static_folder)
        # Tell connected displays so a photo sent from a phone appears in the
        # slideshow rotation without waiting for the next 10-minute rescan.
        if uploaded_files:
            broker.publish(events.PHOTOS_CHANGED, count=len(uploaded_files))
    except Exception as e:
        logger.error(f"Failed to sync photo database: {e}")
        errors.append("Failed to update photo database")

    # One summary line per request rather than five-plus: this app runs on a
    # Raspberry Pi logging to an SD card.
    logger.info(
        "Upload complete: %d photo(s) stored, %d error(s)",
        len(uploaded_files),
        len(errors),
    )

    return jsonify(
        {
            "success": True,
            "uploaded": uploaded_files,
            "errors": errors,
            "count": len(uploaded_files),
        }
    )


def _parse_pagination_args(args):
    """Parse and clamp the pagination query parameters.

    Values that are numeric but out of range are clamped to sane bounds so a
    stray ``per_page=0`` cannot cause a ZeroDivisionError and a negative page
    cannot produce a nonsense slice. Values that are not integers at all are
    genuinely malformed input and raise, so the caller can answer 400.

    Args:
        args: The request's query-string mapping.

    Returns:
        tuple: (page, per_page), both clamped to valid ranges.

    Raises:
        ValueError: If either parameter is not an integer.
    """
    page = int(args.get("page", 1))
    per_page = int(args.get("per_page", DEFAULT_PER_PAGE))

    page = max(1, page)
    per_page = min(max(1, per_page), MAX_PER_PAGE)

    return page, per_page


@upload_bp.route("/api/photos", methods=["GET"])
@require_upload_token
def list_photos():
    """List all photos with pagination support.

    Requires an upload token, matching the POST and DELETE handlers on the
    same resource: the filenames, sizes and timestamps returned here are the
    exact inputs the token-protected DELETE endpoint takes, so leaving the
    read side open hands an unauthenticated LAN client the whole target list.
    The /upload/manage page is reached from a QR code whose URL carries
    ?token=..., and its loadPhotos() already forwards that token on this
    request, so the real flow is unaffected.
    """
    try:
        page, per_page = _parse_pagination_args(request.args)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid pagination parameters"}), 400

    try:
        photos_dir = os.path.join(current_app.static_folder, "photos")
        if not os.path.exists(photos_dir):
            return jsonify(
                {
                    "photos": [],
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "pages": 1,
                }
            )

        # Get all photo files
        photo_files = []
        for filename in os.listdir(photos_dir):
            if allowed_file(filename) and not filename.startswith("thumbnails"):
                filepath = os.path.join(photos_dir, filename)
                if os.path.isfile(filepath):
                    photo_files.append(
                        {
                            "filename": filename,
                            "size": os.path.getsize(filepath),
                            "modified": os.path.getmtime(filepath),
                        }
                    )

        # Sort by modification time (newest first)
        photo_files.sort(key=lambda x: x["modified"], reverse=True)

        # Paginate
        total = len(photo_files)
        start = (page - 1) * per_page
        end = start + per_page
        photos_page = photo_files[start:end]

        return jsonify(
            {
                "photos": photos_page,
                "total": total,
                "page": page,
                "per_page": per_page,
                # per_page is clamped to >= 1, so this cannot divide by zero.
                "pages": max(1, (total + per_page - 1) // per_page),
            }
        )

    except Exception as e:
        logger.error(f"Failed to list photos: {e}")
        return jsonify({"error": "Failed to retrieve photos"}), 500


@upload_bp.route("/api/photos/<filename>", methods=["DELETE"])
@require_upload_token
def delete_photo(filename):
    """Delete a specific photo."""
    try:
        filename = secure_filename(filename)
        photos_dir = os.path.join(current_app.static_folder, "photos")
        filepath = os.path.join(photos_dir, filename)

        if not os.path.exists(filepath):
            return jsonify({"error": "Photo not found"}), 404

        # Delete main photo
        os.remove(filepath)

        # Delete thumbnail if it exists
        thumbnails_dir = os.path.join(photos_dir, "thumbnails")
        thumb_name = filename.rsplit(".", 1)[0] + "_thumb.jpg"
        thumb_path = os.path.join(thumbnails_dir, thumb_name)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

        # Sync database
        slideshow_db.sync_photos(current_app.static_folder)
        # A deleted photo must leave the rotation promptly, or the display
        # keeps serving a file that no longer exists.
        broker.publish(events.PHOTOS_CHANGED, deleted=filename)

        logger.info(f"Deleted photo: {filename}")
        return jsonify({"success": True, "message": f"Photo {filename} deleted"})

    except Exception as e:
        logger.error(f"Failed to delete photo {filename}: {e}")
        return jsonify({"error": "Failed to delete photo"}), 500


@upload_bp.route("/manage")
def manage_photos():
    """Render the photo management page."""
    # Never log request.args here: the upload token is passed as ?token=...
    logger.debug("Photo management page accessed from %s", request.remote_addr)

    now = datetime.datetime.now()
    from src.config import get_config

    config = get_config()
    family_name = config.get("app.family_name", "Family")

    return render_template(
        "photo_manage.html",
        current_year=now.year,
        current_month=now.month,
        family_name=family_name,
    )


def get_local_ip():
    """Get the local IP address of the server."""
    try:
        # Create a socket to get the local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


@upload_bp.route("/test-token")
@require_upload_token
def test_token():
    """Simple endpoint to test token validation."""
    return jsonify(
        {"success": True, "message": "Token is valid!", "ip": request.remote_addr}
    )


@upload_bp.route("/qrcode")
@rate_limit_upload
def generate_qrcode():
    """Generate a QR code with secure token for the photo upload page.

    Rate limited because every call mints a live upload token. The endpoint is
    unauthenticated by necessity -- it is how a phone gets its first credential
    -- so without a limit any LAN client could grow the token table without
    bound: 200 plain GETs produced 200 live tokens. The token manager reclaims
    expired entries, but only as fast as they expire.

    The UI fetches this only when someone presses the QR button, so the
    existing per-client allowance is far above any legitimate use.
    """
    if not QRCODE_AVAILABLE:
        return jsonify({"error": "QR code generation not available"}), 500

    try:
        # Import and use token_manager directly
        from .auth import token_manager

        # If token_manager is not initialized, initialize it now
        if token_manager is None:
            from .auth import init_token_manager

            token_manager = init_token_manager(current_app)

        # Get the local IP address
        host = get_local_ip()
        port = request.environ.get("SERVER_PORT", 5000)
        client_ip = request.remote_addr

        # Build the full URL
        if host == "localhost" or host.startswith("127."):
            # For localhost, try to get the actual network IP
            host = get_local_ip()

        # Allow override via environment variable for testing
        override_host = os.environ.get("CALENDAR_UPLOAD_HOST")
        if override_host:
            host = override_host
            logger.info(f"Using override host: {host}")

        # Generate a secure token for this session
        token_data = token_manager.generate_token(ip_address=client_ip)
        token = token_data["token"]
        expiry = token_data["expiry"]

        # Create the URL with embedded token.
        # host is resolved by get_local_ip() or CALENDAR_UPLOAD_HOST, never from the
        # request's Host header, and the URL is only encoded into a QR image, not fetched.
        # nosemgrep: python.flask.security.injection.tainted-url-host.tainted-url-host
        base_url = f"http://{host}:{port}/upload/manage"
        upload_url = generate_upload_url(base_url, token)

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(upload_url)
        qr.make(fit=True)

        # Create an image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64 for embedding in HTML
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        # Calculate minutes until expiry
        minutes_valid = int((expiry - datetime.datetime.now().timestamp()) / 60)

        return jsonify(
            {
                "success": True,
                "qrcode": f"data:image/png;base64,{img_str}",
                "url": upload_url,
                "expires_in": minutes_valid,
                "message": f"This QR code is valid for {minutes_valid} minutes",
            }
        )

    except Exception as e:
        logger.error(f"Failed to generate QR code: {e}")
        return jsonify({"error": "Failed to generate QR code"}), 500
