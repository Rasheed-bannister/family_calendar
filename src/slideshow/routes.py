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
        # Distinguish between "no photos uploaded" vs an actual error.
        # Return 200 with empty: true so the frontend knows this is a normal state,
        # not a transient error worth retrying aggressively.
        count = slideshow_db.get_photo_count()
        return jsonify({"url": None, "empty": count == 0}), 200
