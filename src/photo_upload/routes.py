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

from ..slideshow import database as slideshow_db
from .auth import (
    generate_upload_url,
    rate_limit_upload,
    require_upload_token,
)

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
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
THUMBNAIL_SIZE = (300, 300)

logger = logging.getLogger(__name__)


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
            except:
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
            except:
                pass
            return None
        return image_path


@upload_bp.route("/")
def upload_page():
    """Render the photo upload page."""
    logger.info(f"Photo upload page accessed from {request.remote_addr}")
    logger.info(f"Query parameters: {dict(request.args)}")

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
    logger.info(f"Upload request received from {request.remote_addr}")
    logger.info(f"Request files: {list(request.files.keys())}")
    logger.info(f"Request form: {dict(request.form)}")

    if "photos" not in request.files:
        logger.warning("No 'photos' field in request files")
        return jsonify({"error": "No photos provided"}), 400

    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No photos selected"}), 400

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
            logger.info(f"Saved uploaded file: {unique_filename}")

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
                except:
                    pass

    # Sync database with new photos
    try:
        slideshow_db.sync_photos(current_app.static_folder)
        logger.info("Photo database synced successfully")
    except Exception as e:
        logger.error(f"Failed to sync photo database: {e}")
        errors.append("Failed to update photo database")

    return jsonify(
        {
            "success": True,
            "uploaded": uploaded_files,
            "errors": errors,
            "count": len(uploaded_files),
        }
    )


@upload_bp.route("/api/photos", methods=["GET"])
def list_photos():
    """List all photos with pagination support."""
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))

        photos_dir = os.path.join(current_app.static_folder, "photos")
        if not os.path.exists(photos_dir):
            return jsonify({"photos": [], "total": 0, "page": 1, "pages": 1})

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
                "pages": (total + per_page - 1) // per_page,
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

        logger.info(f"Deleted photo: {filename}")
        return jsonify({"success": True, "message": f"Photo {filename} deleted"})

    except Exception as e:
        logger.error(f"Failed to delete photo {filename}: {e}")
        return jsonify({"error": "Failed to delete photo"}), 500


@upload_bp.route("/manage")
def manage_photos():
    """Render the photo management page."""
    logger.info(f"Photo management page accessed from {request.remote_addr}")
    logger.info(f"Query parameters: {dict(request.args)}")

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
def generate_qrcode():
    """Generate a QR code with secure token for the photo upload page."""
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

        # Create the URL with embedded token
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
