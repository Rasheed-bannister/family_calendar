from flask import Blueprint, jsonify, url_for

from . import database as slideshow_db

slideshow_bp = Blueprint("slideshow", __name__, url_prefix="/api")


@slideshow_bp.route("/random-photo")
def random_photo():
    """API endpoint to get a random background photo URL."""
    filename = slideshow_db.get_random_photo_filename()
    if filename:
        try:
            photo_url = url_for(
                "static", filename=f"{slideshow_db.PHOTOS_STATIC_REL_PATH}/{filename}"
            )
            return jsonify({"url": photo_url})
        except Exception:
            return jsonify({"error": "Could not generate photo URL"}), 500
    else:
        return jsonify({"error": "No photos found in database"}), 404
