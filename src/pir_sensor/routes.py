"""
PIR Sensor Routes for Calendar Application
Provides endpoints for PIR sensor status and activity reporting
"""

import json
import logging
import threading
import time
from queue import Empty, Full, Queue

from flask import Blueprint, Response, jsonify

from .sensor import (
    add_motion_callback,
    get_pir_sensor,
    start_pir_monitoring,
    stop_pir_monitoring,
)

pir_bp = Blueprint("pir", __name__, url_prefix="/pir")

# Per-client SSE queues with bounded size
_sse_clients: list[Queue] = []
_sse_clients_lock = threading.Lock()
_MAX_QUEUE_SIZE = 50


def _add_sse_client() -> Queue:
    """Register a new SSE client and return its event queue."""
    q: Queue = Queue(maxsize=_MAX_QUEUE_SIZE)
    with _sse_clients_lock:
        _sse_clients.append(q)
    return q


def _remove_sse_client(q: Queue) -> None:
    """Unregister an SSE client."""
    with _sse_clients_lock:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


def motion_detected_sse():
    """Callback function: broadcast motion event to all connected SSE clients."""
    event_data = {
        "type": "motion_detected",
        "timestamp": time.time(),
        "data": "Motion detected by PIR sensor",
    }
    with _sse_clients_lock:
        for q in _sse_clients:
            try:
                q.put_nowait(event_data)
            except Full:
                # Client is too slow — drop oldest event and enqueue new one
                try:
                    q.get_nowait()
                    q.put_nowait(event_data)
                except (Empty, Full):
                    pass


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
    """Server-Sent Events endpoint for real-time PIR sensor events"""
    client_queue = _add_sse_client()

    def event_stream():
        try:
            while True:
                try:
                    event = client_queue.get(timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except Empty:
                    # Send heartbeat to keep connection alive
                    heartbeat = {"type": "heartbeat", "timestamp": time.time()}
                    yield f"data: {json.dumps(heartbeat)}\n\n"
                except Exception as e:
                    logging.error(f"Error in PIR SSE stream: {e}")
                    break
        finally:
            _remove_sse_client(client_queue)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
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
