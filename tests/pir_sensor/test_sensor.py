"""Tests for src/pir_sensor/sensor.py.

Real GPIO only exists on a Raspberry Pi, so ``MotionSensor`` is replaced with
a fake class that records how it was driven. Everything the module decides
for itself is covered: open-once semantics, loud failure, debouncing, the
callback registry and the process-wide singleton.
"""

from unittest.mock import Mock

import pytest

from src.pir_sensor import sensor as sensor_module
from src.pir_sensor.sensor import (
    PIRSensor,
    add_motion_callback,
    build_sensor,
    get_pir_sensor,
    initialize_pir_sensor,
    remove_motion_callback,
    set_pir_sensor,
    shutdown_pir_sensor,
    trigger_motion_callbacks,
)


class FakeMotionSensor:
    """Stand-in for gpiozero.MotionSensor."""

    instances: list = []
    fail_with: Exception | None = None

    def __init__(self, pin, **kwargs):
        if FakeMotionSensor.fail_with is not None:
            raise FakeMotionSensor.fail_with
        self.pin = pin
        self.kwargs = kwargs
        self.when_motion = None
        self.closed = False
        self.pin_factory = object()
        self.value = 0
        FakeMotionSensor.instances.append(self)

    def close(self):
        self.closed = True


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StubConfig:
    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture(autouse=True)
def isolate_module_globals():
    """Restore the singleton and the callback list after every test.

    src/pir_sensor/routes.py registers its SSE callback at import time, so
    the list is restored in place rather than cleared.
    """
    saved_callbacks = list(sensor_module._motion_callbacks)
    saved_sensor = sensor_module._pir_sensor
    yield
    sensor_module._motion_callbacks[:] = saved_callbacks
    sensor_module._pir_sensor = saved_sensor


@pytest.fixture
def gpio(monkeypatch):
    """Pretend gpiozero is installed, backed by FakeMotionSensor."""
    FakeMotionSensor.instances = []
    FakeMotionSensor.fail_with = None
    monkeypatch.setattr(sensor_module, "HAS_GPIO", True)
    monkeypatch.setattr(sensor_module, "MotionSensor", FakeMotionSensor)
    return FakeMotionSensor


@pytest.fixture
def no_gpio(monkeypatch):
    monkeypatch.setattr(sensor_module, "HAS_GPIO", False)
    monkeypatch.setattr(sensor_module, "MotionSensor", None)


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(sensor_module, "time", fake)
    return fake


@pytest.fixture
def no_callbacks():
    sensor_module._motion_callbacks.clear()
    return sensor_module._motion_callbacks


class TestOpen:
    def test_opens_hardware_once(self, gpio):
        s = PIRSensor(pin=18, debounce_seconds=1.0)
        assert s.open() is True
        assert s.available is True
        assert s.error is None
        assert s.healthy is True
        assert s.pin_factory == "object"
        assert len(gpio.instances) == 1
        assert gpio.instances[0].pin == 18
        assert gpio.instances[0].when_motion == s._on_motion

    def test_second_open_does_not_reopen_the_pin(self, gpio):
        s = PIRSensor(pin=18)
        s.open()
        assert s.open() is True
        assert len(gpio.instances) == 1

    def test_hardware_failure_is_recorded_and_unhealthy(self, gpio, caplog):
        gpio.fail_with = RuntimeError("GPIO18 is already in use")
        s = PIRSensor(pin=18)
        with caplog.at_level("ERROR"):
            assert s.open() is False
        assert s.available is False
        assert s.healthy is False
        assert "already in use" in s.error
        assert "RuntimeError" in s.error
        assert "cannot open GPIO 18" in caplog.text

    def test_failure_never_latches_into_silent_simulation(self, gpio):
        """After a failed open, status keeps saying so; nothing pretends to work."""
        gpio.fail_with = RuntimeError("EPERM")
        s = PIRSensor(pin=18)
        s.open()
        status = s.status()
        assert status["available"] is False
        assert status["simulation"] is False
        assert status["error"]

    def test_simulation_mode_opens_nothing_and_is_healthy(self, gpio):
        s = PIRSensor(pin=18, simulation=True)
        assert s.open() is False
        assert s.available is False
        assert s.healthy is True
        assert gpio.instances == []

    def test_disabled_opens_nothing_and_is_healthy(self, gpio):
        s = PIRSensor(pin=18, enabled=False)
        assert s.open() is False
        assert s.healthy is True
        assert gpio.instances == []

    @pytest.mark.parametrize("pin", [99, -1, "18", None])
    def test_invalid_pin_is_an_error(self, gpio, pin):
        s = PIRSensor(pin=pin)
        assert s.open() is False
        assert "Invalid GPIO pin" in s.error
        assert s.healthy is False
        assert gpio.instances == []

    def test_missing_gpiozero_is_an_error(self, no_gpio):
        s = PIRSensor(pin=18)
        assert s.open() is False
        assert "gpiozero" in s.error
        assert s.healthy is False
        assert s.status()["gpiozero_installed"] is False


class TestClose:
    def test_close_releases_the_pin(self, gpio):
        s = PIRSensor(pin=18)
        s.open()
        handle = gpio.instances[0]
        s.close()
        assert handle.closed is True
        assert handle.when_motion is None
        assert s.available is False
        assert s._sensor is None

    def test_close_is_idempotent(self, gpio):
        s = PIRSensor(pin=18)
        s.open()
        s.close()
        s.close()
        assert len(gpio.instances) == 1

    def test_reopen_after_close_claims_a_fresh_handle(self, gpio):
        s = PIRSensor(pin=18)
        s.open()
        s.close()
        assert s.open() is True
        assert len(gpio.instances) == 2


class TestDebounce:
    def test_bursts_within_debounce_collapse_to_one_event(self, clock, no_callbacks):
        received = []
        add_motion_callback(lambda: received.append(clock.now))
        s = PIRSensor(pin=18, debounce_seconds=2.0, simulation=True)

        s._on_motion()
        clock.advance(0.5)
        s._on_motion()
        clock.advance(1.0)
        s._on_motion()

        assert received == [1000.0]
        assert s.motion_count == 1

    def test_event_after_debounce_is_delivered(self, clock, no_callbacks):
        received = []
        add_motion_callback(lambda: received.append(clock.now))
        s = PIRSensor(pin=18, debounce_seconds=2.0, simulation=True)

        s._on_motion()
        clock.advance(2.0)
        s._on_motion()

        assert received == [1000.0, 1002.0]
        assert s.motion_count == 2

    def test_simulate_motion_uses_the_same_path(self, clock, no_callbacks):
        cb = Mock()
        add_motion_callback(cb)
        s = PIRSensor(pin=18, simulation=True)
        s.simulate_motion()
        s.simulate_motion()  # debounced
        assert cb.call_count == 1
        assert s.last_motion_at == 1000.0

    def test_status_reports_seconds_since_motion(self, clock):
        s = PIRSensor(pin=18, simulation=True)
        assert s.status()["seconds_since_motion"] is None
        s.simulate_motion()
        clock.advance(4.25)
        assert s.status()["seconds_since_motion"] == 4.2


class TestStatus:
    def test_shape(self, gpio):
        s = PIRSensor(pin=4, debounce_seconds=1.5)
        s.open()
        status = s.status()
        assert status == {
            "enabled": True,
            "simulation": False,
            "available": True,
            "pin": 4,
            "pin_factory": "object",
            "error": None,
            "gpiozero_installed": True,
            "motion_count": 0,
            "seconds_since_motion": None,
        }


class TestCallbacks:
    def test_add_is_deduplicated(self, no_callbacks):
        cb = Mock()
        add_motion_callback(cb)
        add_motion_callback(cb)
        trigger_motion_callbacks()
        assert cb.call_count == 1

    def test_remove(self, no_callbacks):
        cb = Mock()
        add_motion_callback(cb)
        remove_motion_callback(cb)
        remove_motion_callback(cb)  # removing twice is fine
        trigger_motion_callbacks()
        cb.assert_not_called()

    def test_failing_callback_does_not_stop_the_others(self, no_callbacks, caplog):
        bad = Mock(side_effect=RuntimeError("boom"))
        good = Mock()
        add_motion_callback(bad)
        add_motion_callback(good)
        with caplog.at_level("ERROR"):
            trigger_motion_callbacks()
        good.assert_called_once()
        assert "Error in motion callback" in caplog.text


class TestSingleton:
    def test_build_sensor_reads_config(self):
        config = StubConfig(
            **{
                "pir_sensor.gpio_pin": 22,
                "pir_sensor.debounce_time": 0.75,
                "pir_sensor.simulation_mode": True,
                "pir_sensor.enabled": False,
            }
        )
        s = build_sensor(config)
        assert (s.pin, s.debounce_seconds, s.simulation, s.enabled) == (
            22,
            0.75,
            True,
            False,
        )

    def test_build_sensor_defaults(self):
        s = build_sensor(StubConfig())
        assert (s.pin, s.debounce_seconds, s.simulation, s.enabled) == (
            18,
            2.0,
            False,
            True,
        )

    def test_initialize_opens_and_installs(self, gpio):
        s = initialize_pir_sensor(StubConfig(**{"pir_sensor.gpio_pin": 18}))
        assert get_pir_sensor() is s
        assert s.available is True

    def test_initialize_replaces_and_closes_the_previous_sensor(self, gpio):
        first = initialize_pir_sensor(StubConfig())
        second = initialize_pir_sensor(StubConfig())
        assert first is not second
        assert gpio.instances[0].closed is True
        assert get_pir_sensor() is second

    def test_set_and_shutdown(self, gpio):
        s = PIRSensor(pin=18)
        s.open()
        set_pir_sensor(s)
        assert get_pir_sensor() is s
        shutdown_pir_sensor()
        assert get_pir_sensor() is None
        assert gpio.instances[0].closed is True

    def test_shutdown_without_sensor_is_a_noop(self):
        set_pir_sensor(None)
        shutdown_pir_sensor()
        assert get_pir_sensor() is None
