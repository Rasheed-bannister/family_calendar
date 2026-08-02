"""
PIR Sensor Routes for Calendar Application
Provides endpoints for PIR sensor status and activity reporting
"""

import functools
import logging
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, request

from src import events
from src.events import broker

from .sensor import (
    add_motion_callback,
    get_pir_sensor,
    start_pir_monitoring,
    stop_pir_monitoring,
)

pir_bp = Blueprint("pir", __name__, url_prefix="/pir")


def motion_detected_sse():
    """Callback function: broadcast motion to every connected client."""
    broker.publish(events.MOTION_DETECTED, data="Motion detected by PIR sensor")


# Register the SSE callback
add_motion_callback(motion_detected_sse)


# --- Access control for the state-changing endpoints -----------------------
#
# /start, /stop and /trigger_test change what the whole household sees: they
# can switch motion wake-up off, or fan fake motion out to every connected
# display through the shared broker. The app has no login and the frontend
# calls /start and /stop unauthenticated on every page load, so a token scheme
# would mean changing the frontend and storing a secret on a wall display for
# little gain against someone who is already on the LAN.
#
# What is worth blocking is the reachable attack: a page in a browser on the
# LAN quietly POSTing to the calendar. A cross-site POST with no preflight
# (form encoding or text/plain) would otherwise be executed. Browsers attach
# Origin to those requests, so comparing it against the host the request
# arrived on rejects them while leaving the display's own same-origin calls
# untouched. Requests with no Origin and no Referer (curl, scripts, the
# deployment's own health checks) are allowed through: this is a CSRF guard,
# not authentication, and it does not pretend otherwise.


def _origin_allowed() -> bool:
    """True unless the request demonstrably came from another site's page."""
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source:
        # No browser context claimed. Nothing to check against.
        return True
    # "null" (sandboxed iframe, file://) parses to an empty netloc and is
    # treated as foreign rather than as "no origin".
    return urlsplit(source).netloc == request.host


def same_origin_required(view):
    """Reject a state-changing PIR call made from another site's page."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not _origin_allowed():
            logging.warning(
                "Rejected cross-origin PIR control request (Origin=%r, Referer=%r)",
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
    """True when the fake-motion endpoint may be used.

    /trigger_test exists for the hidden debug panel in index.html. On a
    deployed display it is purely an amplifier -- anything that reaches it can
    spam every connected browser -- so it is off unless the install is
    explicitly in debug or non-production mode. Failing to read the config
    fails closed.
    """
    try:
        from src.config import get_config

        config = get_config()
        return bool(config.get("app.debug", False)) or not config.is_production()
    except Exception as e:  # pragma: no cover - config is loaded at startup
        logging.error(f"Could not determine PIR test endpoint availability: {e}")
        return False


@pir_bp.route("/status", methods=["GET"])
def get_pir_status():
    """Get PIR sensor monitoring status"""
    sensor = get_pir_sensor()
    if not sensor:
        return jsonify(
            {"status": "not_initialized", "monitoring": False, "gpio_available": False}
        )

    return jsonify(
        {
            "status": "initialized",
            "monitoring": sensor.is_monitoring,
            "gpio_available": sensor.gpio_available,
            "pin": sensor.pin,
        }
    )


@pir_bp.route("/start", methods=["POST"])
@same_origin_required
def start_monitoring():
    """Start PIR sensor monitoring"""
    try:
        success = start_pir_monitoring()
        if success:
            return jsonify({"success": True, "message": "PIR monitoring started"})
        else:
            return (
                jsonify(
                    {"success": False, "message": "Failed to start PIR monitoring"}
                ),
                500,
            )
    except Exception as e:
        logging.error(f"Error starting PIR monitoring: {e}")
        return (
            jsonify({"success": False, "message": "Failed to start PIR monitoring"}),
            500,
        )


@pir_bp.route("/stop", methods=["POST"])
@same_origin_required
def stop_monitoring():
    """Stop PIR sensor monitoring"""
    try:
        stop_pir_monitoring()
        return jsonify({"success": True, "message": "PIR monitoring stopped"})
    except Exception as e:
        logging.error(f"Error stopping PIR monitoring: {e}")
        return (
            jsonify({"success": False, "message": "Failed to stop PIR monitoring"}),
            500,
        )


@pir_bp.route("/events")
def pir_events():
    """Legacy motion-only SSE stream.

    Superseded by ``GET /events``, which carries motion plus data-change
    notifications on a single connection. Kept because Flask's threaded
    server holds a thread per open stream, so any client still on this
    endpoint should be moved rather than left to open a second one.
    """
    return Response(
        broker.stream(only=(events.MOTION_DETECTED,)),
        mimetype="text/event-stream",
        headers=events.sse_headers(),
    )


@pir_bp.route("/trigger_test", methods=["POST"])
@same_origin_required
def trigger_test_motion():
    """Test endpoint to simulate motion detection (debug installs only)."""
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

    try:
        motion_detected_sse()
        return jsonify({"success": True, "message": "Test motion triggered"})
    except Exception as e:
        logging.error(f"Error triggering test motion: {e}")
        return (
            jsonify({"success": False, "message": "Failed to trigger test motion"}),
            500,
        )


@pir_bp.route("/diagnostics", methods=["GET"])
def run_diagnostics():
    """Run PIR sensor diagnostics and return structured results."""
    from src.pir_sensor.diagnostics import run_all_checks

    try:
        results = run_all_checks()
        return jsonify(results)
    except Exception as e:
        logging.error(f"Error running PIR diagnostics: {e}")
        return jsonify({"error": "Failed to run PIR diagnostics"}), 500
