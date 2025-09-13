"""
Health monitoring routes for Family Calendar application.
Provides health check endpoints and resource monitoring API.
"""

import logging

from flask import Blueprint, jsonify

from src.health_monitor import health_monitor

health_bp = Blueprint("health", __name__, url_prefix="/health")


@health_bp.route("/")
def health_check():
    """
    Basic health check endpoint.
    Returns 200 if the application is running normally.
    """
    try:
        health_status = health_monitor.check_health()

        # Return appropriate HTTP status code based on health
        if health_status["status"] == "healthy":
            return jsonify(health_status), 200
        elif health_status["status"] == "warning":
            return jsonify(health_status), 200  # Still operational
        else:  # critical
            return jsonify(health_status), 503  # Service Unavailable

    except Exception as e:
        logging.error(f"Health check failed: {e}")
        return (
            jsonify(
                {"status": "error", "message": "Health check failed", "details": str(e)}
            ),
            500,
        )


@health_bp.route("/detailed")
def detailed_health():
    """
    Detailed health information including system resources.
    """
    try:
        health_status = health_monitor.check_health()
        system_info = health_monitor.get_system_info()
        db_status = health_monitor.get_database_status()

        return (
            jsonify(
                {"health": health_status, "system": system_info, "databases": db_status}
            ),
            200,
        )

    except Exception as e:
        logging.error(f"Detailed health check failed: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Detailed health check failed",
                    "details": str(e),
                }
            ),
            500,
        )


@health_bp.route("/system")
def system_resources():
    """
    Current system resource usage.
    """
    try:
        system_info = health_monitor.get_system_info()
        return jsonify(system_info), 200

    except Exception as e:
        logging.error(f"System info failed: {e}")
        return (
            jsonify({"error": "Failed to get system information", "details": str(e)}),
            500,
        )


@health_bp.route("/databases")
def database_status():
    """
    Database files status and accessibility.
    """
    try:
        db_status = health_monitor.get_database_status()
        return jsonify(db_status), 200

    except Exception as e:
        logging.error(f"Database status check failed: {e}")
        return (
            jsonify({"error": "Failed to check database status", "details": str(e)}),
            500,
        )


@health_bp.route("/errors")
def error_summary():
    """
    Application error summary and statistics.
    """
    try:
        return (
            jsonify(
                {
                    "total_errors": health_monitor.error_count,
                    "critical_errors": len(health_monitor.critical_errors),
                    "last_error_time": (
                        health_monitor.last_error_time.isoformat()
                        if health_monitor.last_error_time
                        else None
                    ),
                    "recent_critical_errors": health_monitor._get_recent_critical_errors(),
                    "restart_threshold": health_monitor.restart_threshold,
                    "should_restart": health_monitor.should_restart(),
                }
            ),
            200,
        )

    except Exception as e:
        logging.error(f"Error summary failed: {e}")
        return jsonify({"error": "Failed to get error summary", "details": str(e)}), 500


@health_bp.route("/monitoring/enable", methods=["POST"])
def enable_monitoring():
    """
    Enable health monitoring.
    """
    try:
        health_monitor.enable_monitoring()
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Health monitoring enabled",
                    "monitoring_enabled": True,
                }
            ),
            200,
        )

    except Exception as e:
        logging.error(f"Failed to enable monitoring: {e}")
        return jsonify({"error": "Failed to enable monitoring", "details": str(e)}), 500


@health_bp.route("/monitoring/disable", methods=["POST"])
def disable_monitoring():
    """
    Disable health monitoring.
    """
    try:
        health_monitor.disable_monitoring()
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Health monitoring disabled",
                    "monitoring_enabled": False,
                }
            ),
            200,
        )

    except Exception as e:
        logging.error(f"Failed to disable monitoring: {e}")
        return (
            jsonify({"error": "Failed to disable monitoring", "details": str(e)}),
            500,
        )
