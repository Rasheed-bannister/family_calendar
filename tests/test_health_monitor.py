"""Tests for src/health_monitor.py."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.health_monitor import HealthMonitor


@pytest.fixture
def monitor():
    """Create a fresh HealthMonitor instance."""
    return HealthMonitor()


class TestRecordError:
    """Tests for error recording."""

    def test_increments_error_count(self, monitor):
        monitor.record_error("test", "message")
        assert monitor.error_count == 1
        monitor.record_error("test", "message2")
        assert monitor.error_count == 2

    def test_records_last_error_time(self, monitor):
        assert monitor.last_error_time is None
        monitor.record_error("test", "message")
        assert monitor.last_error_time is not None

    def test_critical_error_stored(self, monitor):
        monitor.record_error("critical_type", "critical msg", is_critical=True)
        assert len(monitor.critical_errors) == 1
        assert monitor.critical_errors[0]["type"] == "critical_type"
        assert monitor.critical_errors[0]["message"] == "critical msg"

    def test_non_critical_not_in_critical_list(self, monitor):
        monitor.record_error("normal", "normal msg", is_critical=False)
        assert len(monitor.critical_errors) == 0

    def test_signals_restart_when_threshold_reached(self, monitor):
        monitor.restart_threshold = 3
        monitor.record_error("err", "msg1", is_critical=True)
        monitor.record_error("err", "msg2", is_critical=True)
        result = monitor.record_error("err", "msg3", is_critical=True)
        assert result is True  # Should signal restart


class TestShouldRestart:
    """Tests for restart threshold logic."""

    def test_no_errors_no_restart(self, monitor):
        assert monitor.should_restart() is False

    def test_below_threshold(self, monitor):
        monitor.restart_threshold = 5
        for i in range(4):
            monitor.record_error("err", f"msg{i}", is_critical=True)
        assert monitor.should_restart() is False

    def test_at_threshold(self, monitor):
        monitor.restart_threshold = 3
        for i in range(3):
            monitor.record_error("err", f"msg{i}", is_critical=True)
        assert monitor.should_restart() is True

    def test_old_errors_ignored(self, monitor):
        """Errors outside the restart window should not count."""
        monitor.restart_threshold = 3
        monitor.restart_window = 600  # 10 minutes

        # Add old errors
        old_time = datetime.now() - timedelta(seconds=700)
        for i in range(5):
            monitor.critical_errors.append(
                {"timestamp": old_time, "type": "err", "message": f"old{i}"}
            )

        assert monitor.should_restart() is False


class TestCleanupOldCriticalErrors:
    """Tests for _cleanup_old_critical_errors."""

    def test_removes_old_errors(self, monitor):
        old_time = datetime.now() - timedelta(seconds=monitor.restart_window * 3)
        monitor.critical_errors = [
            {"timestamp": old_time, "type": "err", "message": "old"}
        ]
        monitor._cleanup_old_critical_errors()
        assert len(monitor.critical_errors) == 0

    def test_keeps_recent_errors(self, monitor):
        recent_time = datetime.now()
        monitor.critical_errors = [
            {"timestamp": recent_time, "type": "err", "message": "recent"}
        ]
        monitor._cleanup_old_critical_errors()
        assert len(monitor.critical_errors) == 1

    def test_enforces_max_count(self, monitor):
        monitor.max_critical_errors = 5
        now = datetime.now()
        for i in range(20):
            monitor.critical_errors.append(
                {"timestamp": now, "type": "err", "message": f"msg{i}"}
            )
        monitor._cleanup_old_critical_errors()
        assert len(monitor.critical_errors) <= 5


class TestCheckHealth:
    """Tests for check_health."""

    @patch.object(HealthMonitor, "get_system_info")
    def test_healthy_system(self, mock_info, monitor):
        mock_info.return_value = {
            "system": {
                "cpu_percent": 20,
                "memory_percent": 40,
                "disk_percent": 50,
            },
            "process": {"memory_mb": 100, "cpu_percent": 5},
        }
        result = monitor.check_health()
        assert result["status"] == "healthy"
        assert len(result["issues"]) == 0

    @patch.object(HealthMonitor, "get_system_info")
    def test_high_cpu_warning(self, mock_info, monitor):
        mock_info.return_value = {
            "system": {
                "cpu_percent": 95,
                "memory_percent": 40,
                "disk_percent": 50,
            },
            "process": {"memory_mb": 100, "cpu_percent": 5},
        }
        result = monitor.check_health()
        assert result["status"] == "warning"
        assert "High CPU usage" in result["issues"]

    @patch.object(HealthMonitor, "get_system_info")
    def test_high_memory_warning(self, mock_info, monitor):
        mock_info.return_value = {
            "system": {
                "cpu_percent": 20,
                "memory_percent": 90,
                "disk_percent": 50,
            },
            "process": {"memory_mb": 100, "cpu_percent": 5},
        }
        result = monitor.check_health()
        assert result["status"] == "warning"
        assert "High memory usage" in result["issues"]

    @patch.object(HealthMonitor, "get_system_info")
    def test_low_disk_critical(self, mock_info, monitor):
        mock_info.return_value = {
            "system": {
                "cpu_percent": 20,
                "memory_percent": 40,
                "disk_percent": 95,
            },
            "process": {"memory_mb": 100, "cpu_percent": 5},
        }
        result = monitor.check_health()
        assert result["status"] == "critical"
        assert "Low disk space" in result["issues"]

    @patch.object(HealthMonitor, "get_system_info")
    def test_high_process_memory_warning(self, mock_info, monitor):
        mock_info.return_value = {
            "system": {
                "cpu_percent": 20,
                "memory_percent": 40,
                "disk_percent": 50,
            },
            "process": {"memory_mb": 600, "cpu_percent": 5},
        }
        result = monitor.check_health()
        assert result["status"] == "warning"
        assert "High process memory usage" in result["issues"]


class TestEnableDisableMonitoring:
    """Tests for enable/disable monitoring."""

    def test_enable(self, monitor):
        monitor.monitoring_enabled = False
        monitor.enable_monitoring()
        assert monitor.monitoring_enabled is True

    def test_disable(self, monitor):
        monitor.disable_monitoring()
        assert monitor.monitoring_enabled is False


class TestHardwareStatus:
    """A PIR that was expected and is not working must show up in /health/."""

    SYSTEM = {
        "system": {"cpu_percent": 20, "memory_percent": 40, "disk_percent": 50},
        "process": {"memory_mb": 100, "cpu_percent": 5},
    }

    @pytest.fixture(autouse=True)
    def isolate_singletons(self):
        from src.display.service import get_display_service, set_display_service
        from src.pir_sensor.sensor import get_pir_sensor, set_pir_sensor

        saved_pir, saved_display = get_pir_sensor(), get_display_service()
        yield
        set_pir_sensor(saved_pir)
        set_display_service(saved_display)

    @patch.object(HealthMonitor, "get_system_info")
    def test_no_sensor_no_service(self, mock_info, monitor):
        from src.display.service import set_display_service
        from src.pir_sensor.sensor import set_pir_sensor

        mock_info.return_value = self.SYSTEM
        set_pir_sensor(None)
        set_display_service(None)
        result = monitor.check_health()
        assert result["status"] == "healthy"
        assert result["hardware"]["pir"] == {"expected": False, "ok": True}
        assert result["hardware"]["display"] == {"running": False}

    @patch.object(HealthMonitor, "get_system_info")
    def test_broken_pir_is_a_warning(self, mock_info, monitor):
        from src.pir_sensor.sensor import PIRSensor, set_pir_sensor

        mock_info.return_value = self.SYSTEM
        broken = PIRSensor(pin=18)
        broken.error = "RuntimeError: EPERM"
        set_pir_sensor(broken)
        result = monitor.check_health()
        assert result["status"] == "warning"
        assert result["issues"] == ["PIR sensor not working (details at /pir/status)"]
        # The raw error stays on /pir/status; /health/ carries no error text.
        assert "EPERM" not in str(result)
        assert result["hardware"]["pir"]["expected"] is True
        assert result["hardware"]["pir"]["ok"] is False

    @patch.object(HealthMonitor, "get_system_info")
    def test_simulation_pir_is_not_an_issue(self, mock_info, monitor):
        from src.pir_sensor.sensor import PIRSensor, set_pir_sensor

        mock_info.return_value = self.SYSTEM
        set_pir_sensor(PIRSensor(pin=18, simulation=True))
        result = monitor.check_health()
        assert result["status"] == "healthy"
        assert result["hardware"]["pir"]["expected"] is False

    @patch.object(HealthMonitor, "get_system_info")
    def test_critical_stays_critical(self, mock_info, monitor):
        from src.pir_sensor.sensor import PIRSensor, set_pir_sensor

        mock_info.return_value = {
            "system": {"cpu_percent": 20, "memory_percent": 40, "disk_percent": 95},
            "process": {"memory_mb": 100, "cpu_percent": 5},
        }
        broken = PIRSensor(pin=18)
        broken.error = "nope"
        set_pir_sensor(broken)
        result = monitor.check_health()
        assert result["status"] == "critical"
        assert len(result["issues"]) == 2

    @patch.object(HealthMonitor, "get_system_info")
    def test_display_service_is_reported(self, mock_info, monitor):
        from src.display.service import set_display_service

        mock_info.return_value = self.SYSTEM

        class FakeService:
            running = True

            def snapshot(self):
                return {
                    "mode": "dimmed",
                    "brightness": 0.6,
                    "backlight": {"backend": "sysfs", "available": True},
                }

        set_display_service(FakeService())
        display = monitor.check_health()["hardware"]["display"]
        assert display == {
            "running": True,
            "mode": "dimmed",
            "brightness": 0.6,
            "backlight": {"backend": "sysfs", "available": True},
        }
