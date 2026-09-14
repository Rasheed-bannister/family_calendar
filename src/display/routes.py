"""HTTP surface of the display state.

``GET  /api/display``           current snapshot
``POST /api/display/activity``  the page saw real input; body ``{"source": ...}``
``POST /api/display/sleep``     jump to the slideshow now (a "show photos" button,
                                and handy for checking a deployment)
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from src.config import get_config

from .service import ensure_display_service

logger = logging.getLogger(__name__)

display_bp = Blueprint("display", __name__, url_prefix="/api/display")

# Sources the page may claim. Anything else is recorded as "browser" so a
# stray string cannot end up in logs verbatim.
_KNOWN_SOURCES = {"touch", "pointer", "keyboard", "wheel", "browser"}


@display_bp.route("", methods=["GET"])
def get_display():
    return jsonify(ensure_display_service(get_config()).snapshot())


@display_bp.route("/activity", methods=["POST"])
def post_activity():
    data = request.get_json(silent=True) or {}
    source = str(data.get("source") or "browser")
    if source not in _KNOWN_SOURCES:
        source = "browser"
    return jsonify(ensure_display_service(get_config()).activity(source))


@display_bp.route("/sleep", methods=["POST"])
def post_sleep():
    return jsonify(ensure_display_service(get_config()).force_slideshow())
