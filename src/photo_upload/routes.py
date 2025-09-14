"""Photo upload routes providing secure mobile photo upload functionality."""

import base64
import contextlib
import datetime
import logging
import os
import socket
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
)
from werkzeug.utils import secure_filename

from src.slideshow import database as slideshow_db
from src.config import get_config

from .auth import (
    generate_upload_url,
    init_token_manager,
    rate_limit_upload,
    require_upload_token,
    token_manager,
)

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
def after_request(response: Response) -> Response:
    """Add CORS headers to all upload responses."""
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add(
        "Access-Control-Allow-Headers",
        "Content-Type,Authorization,X-Upload-Token",
    )
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    return response


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "heic", "heif"}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
THUMBNAIL_SIZE = (300, 300)


def allowed_file(filename: str) -> bool:
    """Check if the file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_thumbnail(image_path: str, thumbnail_path: str) -> str | None:
    """Create a thumbnail for the uploaded image."""
    if not PIL_AVAILABLE:
        logger.warning("PIL not available, skipping thumbnail creation")
        return None

    try:
        with Image.open(image_path) as img:
            # Convert to RGB if needed (handles HEIC/HEIF and RGBA images)
            if img.mode in ["HEIC", "HEIF", "RGBA", "P"]:
                img = img.convert("RGB")  # noqa: PLW2901

            # Create thumbnail maintaining aspect ratio
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

            # Save as JPEG for consistency
            thumbnail_path = thumbnail_path.rsplit(".", 1)[0] + "_thumb.jpg"
            img.save(thumbnail_path, "JPEG", quality=85, optimize=True)

            return thumbnail_path
    except Exception:
        logger.exception("Failed to create thumbnail for %s", image_path)
        return None


def optimize_image(image_path: str) -> str | None:  # noqa: C901
    """Optimize image size and quality for web display."""
    if not PIL_AVAILABLE:
        logger.warning("PIL not available, skipping image optimization")
        return image_path

    try:
        # Check if this is a HEIC/HEIF file by extension
        is_heic = image_path.lower().endswith((".heic", ".heif"))

        if is_heic and not HEIF_AVAILABLE:
            logger.warning(
                "Cannot process HEIC file %s - pillow-heif not available",
                image_path,
            )
            # Try to remove the file since browsers can't display it
            with contextlib.suppress(OSError):
                Path(image_path).unlink()
            return None

        with Image.open(image_path) as img:
            # Always convert HEIC/HEIF to JPEG for browser compatibility
            if is_heic or img.format in ["HEIC", "HEIF"]:
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")  # noqa: PLW2901

                # Save as JPEG with a new filename
                new_path = image_path.rsplit(".", 1)[0] + ".jpg"
                img.save(new_path, "JPEG", quality=85, optimize=True)

                # Remove original HEIC/HEIF file
                try:
                    Path(image_path).unlink()
                    logger.info("Converted HEIC to JPEG: %s", Path(new_path).name)
                except Exception:
                    logger.exception("Failed to remove original HEIC file")

                return new_path

            # Optimize existing formats
            if img.format in ["JPEG", "PNG", "WEBP"]:
                # Resize if too large (max 2000px on longest side)
                max_size = 2000
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                img.save(image_path, img.format, quality=85, optimize=True)

            return image_path

    except Exception:
        logger.exception("Failed to optimize image %s", image_path)
        # If it's a HEIC file that failed, remove it
        if image_path.lower().endswith((".heic", ".heif")):
            try:
                Path(image_path).unlink()
                logger.info(
                    "Removed incompatible HEIC file: %s",
                    Path(image_path).name,
                )
            except OSError:
                pass
            return None
        return image_path


@upload_bp.route("/")
def upload_page() -> str:
    """Render the photo upload page."""
    logger.info("Photo upload page accessed from %s", request.remote_addr)
    logger.info("Query parameters: %s", dict(request.args))

    now = datetime.datetime.now()  # noqa: DTZ005

    config = get_config()
    family_name = config.get("app.family_name", "Family")

    return render_template(
        "photo_upload.html",
        current_year=now.year,
        current_month=now.month,
        family_name=family_name,
    )


@upload_bp.route("/api/photos", methods=["OPTIONS"])
def upload_photos_preflight() -> Response:
    """Handle CORS preflight requests."""
    response = make_response()
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add(
        "Access-Control-Allow-Headers",
        "Content-Type,Authorization,X-Upload-Token",
    )
    response.headers.add("Access-Control-Allow-Methods", "POST,OPTIONS")
    return response


@upload_bp.route("/api/photos", methods=["POST"])
@require_upload_token
@rate_limit_upload
def upload_photos() -> Response | tuple[Response, int]:  # noqa: C901, PLR0915
    """Handle photo upload from mobile devices."""
    logger.info("Upload request received from %s", request.remote_addr)
    logger.info("Request files: %s", list(request.files.keys()))
    logger.info("Request form: %s", dict(request.form))

    if "photos" not in request.files:
        logger.warning("No 'photos' field in request files")
        return jsonify({"error": "No photos provided"}), 400

    files = request.files.getlist("photos")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No photos selected"}), 400

    uploaded_files = []
    errors = []

    photos_dir = Path(current_app.static_folder or "static") / "photos"
    thumbnails_dir = photos_dir / "thumbnails"
    photos_dir.mkdir(parents=True, exist_ok=True)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        if file.filename == "":
            continue

        if not file.filename or not allowed_file(file.filename):
            errors.append(
                f"Invalid file type: {file.filename}. "
                f"Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
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
        filename = secure_filename(file.filename or "unknown")
        path_obj = Path(filename)
        name, ext = path_obj.stem, path_obj.suffix
        unique_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"

        filepath = photos_dir / unique_filename

        try:
            # Save the uploaded file
            file.save(str(filepath))
            logger.info("Saved uploaded file: %s", unique_filename)

            # Optimize the image
            optimized_path = optimize_image(str(filepath))

            # Check if optimization failed (e.g., incompatible HEIC)
            if optimized_path is None:
                errors.append(
                    f"Unable to process {file.filename} - format not supported",
                )
                continue

            final_filename = Path(optimized_path).name

            # Create thumbnail
            thumbnail_path = thumbnails_dir / final_filename
            create_thumbnail(optimized_path, str(thumbnail_path))

            uploaded_files.append(
                {
                    "filename": final_filename,
                    "original_name": file.filename,
                    "size": Path(optimized_path).stat().st_size,
                },
            )

        except Exception as e:
            logger.exception("Failed to process %s", filename)
            errors.append(f"Failed to save {filename}: {e!s}")
            # Clean up partial file if it exists
            if Path(filepath).exists():
                with contextlib.suppress(OSError):
                    Path(filepath).unlink()

    # Sync database with new photos
    try:
        slideshow_db.sync_photos(current_app.static_folder)
        logger.info("Photo database synced successfully")
    except Exception:
        logger.exception("Failed to sync photo database")
        errors.append("Failed to update photo database")

    return jsonify(
        {
            "success": True,
            "uploaded": uploaded_files,
            "errors": errors,
            "count": len(uploaded_files),
        },
    )


@upload_bp.route("/api/photos", methods=["GET"])
def list_photos() -> Response | tuple[Response, int]:
    """List all photos with pagination support."""
    logger.info("Photos API called from %s with params: %s", request.remote_addr, dict(request.args))
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))

        photos_dir = Path(current_app.static_folder or "static") / "photos"
        if not photos_dir.exists():
            return jsonify({"photos": [], "total": 0, "page": 1, "pages": 1})

        # Get all photo files
        photo_files: list[dict[str, Any]] = []
        for filepath in photos_dir.iterdir():
            if (
                filepath.is_file()
                and allowed_file(filepath.name)
                and not filepath.name.startswith("thumbnails")
            ):
                stat = filepath.stat()
                photo_files.append(
                    {
                        "filename": filepath.name,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    },
                )

        # Sort by modification time (newest first)
        photo_files.sort(key=lambda x: cast("float", x["modified"]), reverse=True)

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
            },
        )

    except Exception:
        logger.exception("Failed to list photos")
        return jsonify({"error": "Failed to retrieve photos"}), 500


@upload_bp.route("/api/photos/<filename>", methods=["DELETE"])
@require_upload_token
def delete_photo(filename: str) -> Response | tuple[Response, int]:
    """Delete a specific photo."""
    try:
        filename = secure_filename(filename)
        photos_dir = Path(current_app.static_folder or "static") / "photos"
        filepath = photos_dir / filename

        if not filepath.exists():
            return jsonify({"error": "Photo not found"}), 404

        # Delete main photo
        Path(filepath).unlink()

        # Delete thumbnail if it exists
        thumbnails_dir = photos_dir / "thumbnails"
        thumb_name = Path(filename).stem + "_thumb.jpg"
        thumb_path = thumbnails_dir / thumb_name
        if thumb_path.exists():
            Path(thumb_path).unlink()

        # Sync database
        slideshow_db.sync_photos(current_app.static_folder)

        logger.info("Deleted photo: %s", filename)
        return jsonify({"success": True, "message": f"Photo {filename} deleted"})

    except Exception:
        logger.exception("Failed to delete photo %s", filename)
        return jsonify({"error": "Failed to delete photo"}), 500


@upload_bp.route("/manage")
def manage_photos() -> str:
    """Render the photo management page."""
    logger.info("Photo management page accessed from %s", request.remote_addr)
    logger.info("Query parameters: %s", dict(request.args))
    token = request.args.get('token')
    if token:
        logger.info("Token received on manage page: %s...", token[:20])
    else:
        logger.warning("No token received on manage page!")

    now = datetime.datetime.now()  # noqa: DTZ005

    config = get_config()
    family_name = config.get("app.family_name", "Family")

    return render_template(
        "photo_manage.html",
        current_year=now.year,
        current_month=now.month,
        family_name=family_name,
    )


def get_local_ip() -> str:
    """Get the local IP address of the server."""
    try:
        # Create a socket to get the local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        return "localhost"
    else:
        return ip


@upload_bp.route("/test-token")
@require_upload_token
def test_token() -> Response:
    """Simple endpoint to test token validation."""
    return jsonify(
        {"success": True, "message": "Token is valid!", "ip": request.remote_addr},
    )


@upload_bp.route("/qrcode")
def generate_qrcode() -> Response | tuple[Response, int]:
    """Generate a QR code with secure token for the photo upload page."""
    if not QRCODE_AVAILABLE:
        return jsonify({"error": "QR code generation not available"}), 500

    try:
        # Use already imported token_manager and init_token_manager
        # If token_manager is not initialized, initialize it now
        tm = init_token_manager(current_app) if token_manager is None else token_manager

        # Get the local IP address
        host = get_local_ip()
        # Get port from request URL or default to 5000
        port = request.environ.get("SERVER_PORT") or request.host.split(":")[-1] if ":" in request.host else "5000"
        client_ip = request.remote_addr

        logger.info("QR Code generation - Host: %s, Port: %s, Client IP: %s", host, port, client_ip)

        # For QR codes, bind token to the server's network IP instead of localhost
        # This allows mobile devices on the same network to access with the token
        token_bind_ip = host if client_ip in ["127.0.0.1", "::1", "localhost"] else client_ip
        logger.info("Token will be bound to IP: %s", token_bind_ip)

        # Build the full URL
        if host == "localhost" or host.startswith("127."):
            # For localhost, try to get the actual network IP
            host = get_local_ip()

        # Allow override via environment variable for testing
        override_host = os.environ.get("CALENDAR_UPLOAD_HOST")
        if override_host:
            host = override_host
            logger.info("Using override host: %s", host)

        # Generate a secure token for this session
        token_data = tm.generate_token(ip_address=token_bind_ip)
        token = token_data["token"]
        expiry = token_data["expiry"]

        logger.info("Generated token: %s..., expires: %s", token[:20], expiry)

        # Create the URL with embedded token
        base_url = f"http://{host}:{port}/upload/manage"
        upload_url = generate_upload_url(base_url, token)

        logger.info("Generated QR code URL: %s", upload_url)

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
        minutes_valid = int(
            (expiry - datetime.datetime.now(datetime.UTC).timestamp()) / 60,
        )

        return jsonify(
            {
                "success": True,
                "qrcode": f"data:image/png;base64,{img_str}",
                "url": upload_url,
                "expires_in": minutes_valid,
                "message": f"This QR code is valid for {minutes_valid} minutes",
            },
        )

    except Exception:
        logger.exception("Failed to generate QR code")
        return jsonify({"error": "Failed to generate QR code"}), 500
