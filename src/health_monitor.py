"""
Health monitoring module for Family Calendar application.
Provides system health checks, resource monitoring, and critical error detection.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import psutil


class HealthMonitor:
    """System health and resource monitoring."""

    def __init__(self):
        self.start_time = time.time()
        self.error_count = 0
        self.last_error_time = None
        self.critical_errors = []
        self.max_critical_errors = 10
        self.restart_threshold = 5  # Restart after 5 critical errors in 10 minutes
        self.restart_window = 600  # 10 minutes
        self.monitoring_enabled = True
        self.lock = threading.Lock()

    def get_system_info(self) -> Dict[str, Any]:
        """Get current system information."""
        try:
            # CPU information
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()

            # Memory information
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_mb = memory.available / (1024 * 1024)
            memory_total_mb = memory.total / (1024 * 1024)

            # Disk information
            disk = psutil.disk_usage("/")
            disk_percent = (disk.used / disk.total) * 100
            disk_free_gb = disk.free / (1024 * 1024 * 1024)
            disk_total_gb = disk.total / (1024 * 1024 * 1024)

            # Process information
            process = psutil.Process()
            process_memory_mb = process.memory_info().rss / (1024 * 1024)
            process_cpu_percent = process.cpu_percent()

            # Application uptime
            uptime_seconds = time.time() - self.start_time
            uptime_hours = uptime_seconds / 3600

            return {
                "timestamp": datetime.now().isoformat(),
                "uptime_seconds": round(uptime_seconds, 2),
                "uptime_hours": round(uptime_hours, 2),
                "system": {
                    "cpu_percent": cpu_percent,
                    "cpu_count": cpu_count,
                    "memory_percent": memory_percent,
                    "memory_available_mb": round(memory_available_mb, 2),
                    "memory_total_mb": round(memory_total_mb, 2),
                    "disk_percent": round(disk_percent, 2),
                    "disk_free_gb": round(disk_free_gb, 2),
                    "disk_total_gb": round(disk_total_gb, 2),
                },
                "process": {
                    "memory_mb": round(process_memory_mb, 2),
                    "cpu_percent": process_cpu_percent,
                    "pid": process.pid,
                    "threads": process.num_threads(),
                },
                "errors": {
                    "total_count": self.error_count,
                    "critical_count": len(self.critical_errors),
                    "last_error_time": (
                        self.last_error_time.isoformat()
                        if self.last_error_time
                        else None
                    ),
                },
            }

        except Exception as e:
            logging.error(f"Error getting system info: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "error": "Failed to collect system information",
                "details": str(e),
            }

    def check_health(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        system_info = self.get_system_info()
        health_status = "healthy"
        issues = []

        if "system" in system_info:
            # Check CPU usage
            if system_info["system"]["cpu_percent"] > 90:
                health_status = "warning"
                issues.append("High CPU usage")

            # Check memory usage
            if system_info["system"]["memory_percent"] > 85:
                health_status = "warning"
                issues.append("High memory usage")

            # Check disk space
            if system_info["system"]["disk_percent"] > 90:
                health_status = "critical"
                issues.append("Low disk space")

            # Check process memory
            if system_info["process"]["memory_mb"] > 512:  # 512MB threshold
                health_status = "warning"
                issues.append("High process memory usage")

            # Check critical errors
            recent_critical_errors = self._get_recent_critical_errors()
            if len(recent_critical_errors) >= self.restart_threshold:
                health_status = "critical"
                issues.append(
                    f"Too many critical errors ({len(recent_critical_errors)} in 10 minutes)"
                )

        return {
            "status": health_status,
            "issues": issues,
            "system_info": system_info,
            "monitoring_enabled": self.monitoring_enabled,
        }

    def record_error(self, error_type: str, message: str, is_critical: bool = False):
        """Record an application error."""
        with self.lock:
            self.error_count += 1
            self.last_error_time = datetime.now()

            if is_critical:
                self.critical_errors.append(
                    {
                        "timestamp": self.last_error_time,
                        "type": error_type,
                        "message": message,
                    }
                )

                # Keep only recent critical errors
                self._cleanup_old_critical_errors()

                logging.error(f"CRITICAL ERROR: {error_type} - {message}")

                # Check if we need to trigger restart
                if self.should_restart():
                    logging.critical(
                        "Critical error threshold reached. Application restart required."
                    )
                    return True  # Signal that restart is needed
            else:
                logging.warning(f"Error recorded: {error_type} - {message}")

        return False

    def should_restart(self) -> bool:
        """Check if application should restart due to critical errors."""
        recent_errors = self._get_recent_critical_errors()
        return len(recent_errors) >= self.restart_threshold

    def _get_recent_critical_errors(self) -> list:
        """Get critical errors from the last restart window."""
        cutoff_time = datetime.now() - timedelta(seconds=self.restart_window)
        return [
            error for error in self.critical_errors if error["timestamp"] > cutoff_time
        ]

    def _cleanup_old_critical_errors(self):
        """Remove old critical errors to prevent memory buildup."""
        cutoff_time = datetime.now() - timedelta(seconds=self.restart_window * 2)
        self.critical_errors = [
            error for error in self.critical_errors if error["timestamp"] > cutoff_time
        ]

        # Also enforce max count
        if len(self.critical_errors) > self.max_critical_errors:
            self.critical_errors = self.critical_errors[-self.max_critical_errors :]

    def get_database_status(self) -> Dict[str, Any]:
        """Check database file status."""
        db_status = {}
        db_files = ["src/slideshow/slideshow.db", "src/chores_app/chores.db"]

        # Add calendar database files (they're dynamically created)
        calendar_db_pattern = "src/calendar_app/calendar_*.db"
        calendar_dbs = list(Path(".").glob(calendar_db_pattern))
        db_files.extend([str(db) for db in calendar_dbs])

        for db_file in db_files:
            if os.path.exists(db_file):
                stat = os.stat(db_file)
                db_status[db_file] = {
                    "exists": True,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "readable": os.access(db_file, os.R_OK),
                    "writable": os.access(db_file, os.W_OK),
                }
            else:
                db_status[db_file] = {
                    "exists": False,
                    "error": "Database file not found",
                }

        return db_status

    def enable_monitoring(self):
        """Enable health monitoring."""
        self.monitoring_enabled = True
        logging.info("Health monitoring enabled")

    def disable_monitoring(self):
        """Disable health monitoring."""
        self.monitoring_enabled = False
        logging.info("Health monitoring disabled")


# Global health monitor instance
health_monitor = HealthMonitor()
