"""
PIR Sensor Routes for Calendar Application
Provides endpoints for PIR sensor status and activity reporting
"""

import json
import logging
import time
from queue import Empty, Queue

from flask import Blueprint, Response, jsonify, request

from .sensor import (
    add_motion_callback,
    get_pir_sensor,
    start_pir_monitoring,
    stop_pir_monitoring,
)

pir_bp = Blueprint("pir", __name__, url_prefix="/pir")

# Global queue for SSE events
_sse_queue: Queue = Queue()


def motion_detected_sse():
    """Callback function for SSE events when motion is detected"""
    event_data = {
        "type": "motion_detected",
        "timestamp": time.time(),
        "data": "Motion detected by PIR sensor",
    }
    _sse_queue.put(event_data)


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
        return jsonify({"success": False, "message": str(e)}), 500


@pir_bp.route("/stop", methods=["POST"])
def stop_monitoring():
    """Stop PIR sensor monitoring"""
    try:
        stop_pir_monitoring()
        return jsonify({"success": True, "message": "PIR monitoring stopped"})
    except Exception as e:
        logging.error(f"Error stopping PIR monitoring: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@pir_bp.route("/activity", methods=["POST"])
def report_activity():
    """Endpoint for external PIR sensor activity reporting"""
    try:
        data = request.get_json() or {}
        activity_type = data.get("type", "motion")

        # This endpoint can be used by external PIR sensor systems
        # to report activity to the calendar application

        logging.info(f"PIR activity reported: {activity_type}")

        # The actual activity handling will be done via WebSocket or polling
        # This endpoint just confirms receipt

        return jsonify(
            {
                "success": True,
                "message": "Activity reported",
                "activity_type": activity_type,
            }
        )
    except Exception as e:
        logging.error(f"Error reporting PIR activity: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@pir_bp.route("/events")
def pir_events():
    """Server-Sent Events endpoint for real-time PIR sensor events"""

    def event_stream():
        while True:
            try:
                # Wait for an event with timeout
                event = _sse_queue.get(timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
            except Empty:
                # Send heartbeat to keep connection alive
                yield (
                    'data: {"type": "heartbeat", "timestamp": '
                    + str(time.time())
                    + "}\n\n"
                )
            except Exception as e:
                logging.error(f"Error in PIR SSE stream: {e}")
                break

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@pir_bp.route("/trigger_test", methods=["POST"])
def trigger_test_motion():
    """Test endpoint to simulate motion detection"""
    try:
        # Manually trigger the SSE callback for testing
        motion_detected_sse()
        return jsonify({"success": True, "message": "Test motion triggered"})
    except Exception as e:
        logging.error(f"Error triggering test motion: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
