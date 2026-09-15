"""PIR sensor HTTP surface: status, diagnostics, and a debug-only test trigger.

There is no start/stop endpoint by design; see :mod:`src.pir_sensor.sensor`.
"""

from __future__ import annotations

import functools
import logging
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from src import events
from src.events import broker

from .sensor import add_motion_callback, get_pir_sensor

logger = logging.getLogger(__name__)

pir_bp = Blueprint("pir", __name__, url_prefix="/pir")


def motion_detected_sse() -> None:
    """Broadcast motion to every connected client (for the on-screen badge)."""
    broker.publish(events.MOTION_DETECTED)


add_motion_callback(motion_detected_sse)


def _origin_allowed() -> bool:
    """True unless the request demonstrably came from another site's page.

    A CSRF guard, not authentication: the test trigger fans a fake motion
    event out to every display, so a page on the LAN must not be able to
    POST it cross-site.
    """
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source:
        return True
    return urlsplit(source).netloc == request.host


def same_origin_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not _origin_allowed():
            logger.warning(
                "Rejected cross-origin PIR request (Origin=%r, Referer=%r)",
                request.headers.get("Origin"),
                request.headers.get("Referer"),
            )
            return (
                jsonify({"success": False, "message": "Cross-origin request rejected"}),
                403,
            )
        return view(*args, **kwargs)

    return wrapper


def _test_motion_enabled() -> bool:
    try:
        from src.config import get_config

        config = get_config()
        return bool(config.get("app.debug", False)) or not config.is_production()
    except Exception as e:  # pragma: no cover - config is loaded at startup
        logger.error("Could not determine PIR test endpoint availability: %s", e)
        return False


@pir_bp.route("/status", methods=["GET"])
def get_pir_status():
    sensor = get_pir_sensor()
    if sensor is None:
        return jsonify(
            {
                "initialized": False,
                "enabled": False,
                "simulation": False,
                "available": False,
                "error": "PIR sensor not initialized in this process",
            }
        )
    return jsonify({"initialized": True, **sensor.status()})


@pir_bp.route("/trigger_test", methods=["POST"])
@same_origin_required
def trigger_test_motion():
    """Simulate motion (debug/non-production installs only)."""
    if not _test_motion_enabled():
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Test motion is disabled outside debug mode",
                }
            ),
            403,
        )
    sensor = get_pir_sensor()
    if sensor is not None:
        sensor.simulate_motion()
    else:
        # No sensor object at all (e.g. tooling that skipped the runtime);
        # still fan the event out so the UI path can be exercised.
        from .sensor import trigger_motion_callbacks

        trigger_motion_callbacks()
    return jsonify({"success": True, "message": "Test motion triggered"})


@pir_bp.route("/diagnostics", methods=["GET"])
def run_diagnostics():
    from src.pir_sensor.diagnostics import run_all_checks

    try:
        return jsonify(run_all_checks())
    except Exception as e:
        logger.error("Error running PIR diagnostics: %s", e)
        return jsonify({"error": "Failed to run PIR diagnostics"}), 500
