"""Tests for src/runtime.py, with every collaborator replaced by a fake."""

import threading
from unittest.mock import Mock, patch

import pytest

from src import runtime as runtime_module
from src.pir_sensor import sensor as sensor_module


class FakeDisplay:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.activity_calls = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def activity(self, source):
        self.activity_calls.append(source)


class FakeSensor:
    def __init__(self, healthy=True, error=None):
        self.healthy = healthy
        self.error = error


@pytest.fixture(autouse=True)
def isolate():
    saved_runtime = runtime_module._runtime
    saved_callbacks = list(sensor_module._motion_callbacks)
    saved_sensor = sensor_module._pir_sensor
    runtime_module._runtime = None
    yield
    runtime_module._runtime = saved_runtime
    sensor_module._motion_callbacks[:] = saved_callbacks
    sensor_module._pir_sensor = saved_sensor


@pytest.fixture
def collaborators():
    display = FakeDisplay()
    scheduler = Mock()
    sensor = FakeSensor()
    ingested = threading.Event()

    def fake_sync(static_folder):
        ingested.set()

    with (
        patch("src.display.service.ensure_display_service", return_value=display),
        patch("src.main.start_background_sync", return_value=scheduler),
        patch("src.pir_sensor.sensor.initialize_pir_sensor", return_value=sensor),
        patch("src.slideshow.database.sync_photos", side_effect=fake_sync),
        patch("src.runtime.atexit.register") as atexit_register,
        patch("src.runtime.signal.signal") as signal_signal,
        patch("src.display.service.get_display_service", return_value=display),
    ):
        yield {
            "display": display,
            "scheduler": scheduler,
            "sensor": sensor,
            "ingested": ingested,
            "atexit": atexit_register,
            "signal": signal_signal,
        }


def test_start_wires_everything(collaborators):
    app = Mock(static_folder="/tmp/static")
    rt = runtime_module.start_runtime(app)

    assert rt.display is collaborators["display"]
    assert collaborators["display"].started is True
    assert rt.scheduler is collaborators["scheduler"]
    assert rt.pir is collaborators["sensor"]
    assert collaborators["ingested"].wait(2.0)
    collaborators["atexit"].assert_called_once_with(rt.stop)
    collaborators["signal"].assert_called_once()
    assert runtime_module.get_runtime() is rt


def test_start_is_idempotent(collaborators):
    app = Mock(static_folder="/tmp/static")
    first = runtime_module.start_runtime(app)
    second = runtime_module.start_runtime(app)
    assert first is second
    collaborators["atexit"].assert_called_once()


def test_pir_motion_becomes_display_activity(collaborators):
    runtime_module.start_runtime(Mock(static_folder="/tmp/static"))
    assert runtime_module._motion_to_display in sensor_module._motion_callbacks
    sensor_module.trigger_motion_callbacks()
    assert collaborators["display"].activity_calls == ["pir"]


def test_unhealthy_sensor_is_logged_loudly(collaborators, caplog):
    collaborators["sensor"].healthy = False
    collaborators["sensor"].error = "RuntimeError: EPERM"
    with caplog.at_level("ERROR"):
        runtime_module.start_runtime(Mock(static_folder="/tmp/static"))
    assert "PIR sensor is NOT working: RuntimeError: EPERM" in caplog.text


def test_stop_tears_down_in_order(collaborators):
    rt = runtime_module.start_runtime(Mock(static_folder="/tmp/static"))
    with patch("src.pir_sensor.sensor.shutdown_pir_sensor") as shutdown:
        rt.stop()
        rt.stop()  # second call is a no-op
    collaborators["scheduler"].stop.assert_called_once()
    shutdown.assert_called_once()
    assert collaborators["display"].stopped is True
    assert runtime_module._motion_to_display not in sensor_module._motion_callbacks


def test_stop_survives_failing_collaborators(collaborators, caplog):
    rt = runtime_module.start_runtime(Mock(static_folder="/tmp/static"))
    collaborators["scheduler"].stop.side_effect = RuntimeError("boom")
    with caplog.at_level("ERROR"):
        rt.stop()
    assert collaborators["display"].stopped is True
    assert "Error stopping scheduler" in caplog.text


def test_sigterm_off_main_thread_is_tolerated(collaborators):
    collaborators["signal"].side_effect = ValueError("not main thread")
    rt = runtime_module.start_runtime(Mock(static_folder="/tmp/static"))
    assert rt is not None


def test_motion_without_display_service_is_ignored():
    with patch("src.display.service.get_display_service", return_value=None):
        runtime_module._motion_to_display()  # must not raise


def test_ingest_failure_is_logged(collaborators, caplog):
    with patch("src.slideshow.database.sync_photos", side_effect=RuntimeError("disk")):
        with caplog.at_level("ERROR"):
            runtime_module._ingest_photos(Mock(static_folder="/tmp/static"))
    assert "Photo ingest failed" in caplog.text
