from flask import Blueprint, jsonify, url_for

from . import database as slideshow_db
from . import ingest

slideshow_bp = Blueprint("slideshow", __name__, url_prefix="/api/slideshow")


def _photo_payload(photo: slideshow_db.Photo) -> dict:
    return {
        "url": url_for(
            "static",
            filename=(
                f"{slideshow_db.PHOTOS_STATIC_REL_PATH}/"
                f"{ingest.PROCESSED_DIRNAME}/{photo.processed}"
            ),
        ),
        "filename": photo.filename,
        "width": photo.width,
        "height": photo.height,
        "orientation": photo.orientation,
    }


@slideshow_bp.route("/next")
def next_photo():
    """The next photo to display, or ``{"url": null, "empty": true}``."""
    photo = slideshow_db.next_photo()
    if photo is None:
        return jsonify({"url": None, "empty": slideshow_db.get_photo_count() == 0})
    return jsonify(_photo_payload(photo))


@slideshow_bp.route("/settings")
def settings():
    from src.config import get_config

    config = get_config()
    return jsonify(
        {
            "interval_seconds": config.get("slideshow.interval_seconds", 30),
            "transition_seconds": config.get("slideshow.transition_seconds", 2),
            "ken_burns": bool(config.get("slideshow.ken_burns", True)),
            "photo_count": slideshow_db.get_photo_count(),
        }
    )
