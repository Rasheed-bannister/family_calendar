"""
PIR Sensor Routes for Calendar Application
Provides endpoints for PIR sensor status and activity reporting
"""

import logging

from flask import Blueprint, Response, jsonify

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
def trigger_test_motion():
    """Test endpoint to simulate motion detection"""
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
