"""Tests for src/pir_sensor/sensor.py.

The sensor only talks to real GPIO on a Raspberry Pi, so everything here
exercises the simulation-mode paths and the decisions the module makes for
itself: debouncing, callback bookkeeping, pin validation, the monitoring
lifecycle and the once-per-process shutdown hooks. Nothing here touches
hardware, and ``HAS_GPIO`` is only ever patched to check a branch the
constructor decides, never to pretend a sensor exists.
"""

import threading
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from src.pir_sensor import sensor as sensor_module
from src.pir_sensor.sensor import (
    PIRSensor,
    add_motion_callback,
    get_pir_sensor,
    initialize_pir_sensor,
    start_pir_monitoring,
    stop_pir_monitoring,
    trigger_motion_callbacks,
)


class StubConfig:
    """Minimal stand-in for src.config.Config with dotted-key lookup."""

    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


@contextmanager
def stub_config(**values):
    """Patch the global config for the duration of a sensor construction."""
    with patch("src.config.get_config", return_value=StubConfig(**values)):
        yield


def make_sensor(pin=18, callback=None, **config_values):
    """Build a PIRSensor against a stubbed config."""
    with stub_config(**config_values):
        return PIRSensor(pin=pin, callback=callback)


class FakeClock:
    """Stands in for the ``time`` module so debounce needs no real sleeping."""

    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def isolate_module_globals():
    """Keep the module-level sensor, callbacks and hook flags out of the suite.

    src/pir_sensor/routes.py registers its SSE callback at import time and the
    rest of the suite imports it, so the callback list is restored in place
    rather than simply cleared.
    """
    saved_callbacks = list(sensor_module._motion_callbacks)
    saved_sensor = sensor_module._pir_sensor
    saved_atexit = sensor_module._atexit_registered
    saved_sigterm = sensor_module._sigterm_installed
    yield
    sensor_module._motion_callbacks[:] = saved_callbacks
    sensor_module._pir_sensor = saved_sensor
    sensor_module._atexit_registered = saved_atexit
    sensor_module._sigterm_installed = saved_sigterm


@pytest.fixture
def no_callbacks():
    """Start from an empty global callback list (restored by the autouse fixture)."""
    sensor_module._motion_callbacks.clear()
    return sensor_module._motion_callbacks


@pytest.fixture
def clock(monkeypatch):
    """Replace the module's ``time`` reference with a controllable clock."""
    fake = FakeClock()
    monkeypatch.setattr(sensor_module, "time", fake)
    return fake


@pytest.fixture
def no_shutdown_hooks():
    """Stop tests from adding real atexit/SIGTERM handlers to the interpreter."""
    sensor_module._atexit_registered = False
    sensor_module._sigterm_installed = False
    with patch.object(sensor_module.atexit, "register") as register:
        with patch.object(sensor_module.signal, "signal") as signal_signal:
            yield register, signal_signal


class TestConstruction:
    """Configuration is read at construction and decides the mode."""

    def test_config_values_win_over_arguments(self):
        s = make_sensor(
            pin=18,
            **{"pir_sensor.gpio_pin": 4, "pir_sensor.debounce_time": 0.5},
        )
        assert s.pin == 4
        assert s.debounce_time == 0.5

    def test_arguments_are_used_when_config_is_silent(self):
        s = make_sensor(pin=7)
        assert s.pin == 7
        assert s.debounce_time == 2.0

    def test_starts_unmonitored_with_no_gpio_handle(self):
        s = make_sensor()
        assert s.is_monitoring is False
        assert s._sensor is None
        assert s.last_detection_time == 0

    def test_simulation_mode_config_disables_gpio(self, monkeypatch):
        monkeypatch.setattr(sensor_module, "HAS_GPIO", True)
        s = make_sensor(**{"pir_sensor.simulation_mode": True})
        assert s.simulation_mode is True
        assert s.gpio_available is False

    def test_gpio_is_used_when_available_and_pin_is_valid(self, monkeypatch):
        monkeypatch.setattr(sensor_module, "HAS_GPIO", True)
        s = make_sensor(pin=18)
        assert s.gpio_available is True

    def test_missing_gpiozero_means_simulation(self, monkeypatch):
        monkeypatch.setattr(sensor_module, "HAS_GPIO", False)
        s = make_sensor(pin=18)
        assert s.gpio_available is False


class TestPinValidation:
    """A bad pin must degrade to simulation, never take the app down."""

    @pytest.mark.parametrize("pin", [-1, 28, 99, 1000])
    def test_out_of_range_pin_falls_back_to_simulation(self, pin, monkeypatch):
        monkeypatch.setattr(sensor_module, "HAS_GPIO", True)
        s = make_sensor(pin=pin)
        assert s.pin == pin
        assert s.gpio_available is False

    @pytest.mark.parametrize("pin", ["18", None, 18.5])
    def test_non_integer_pin_falls_back_to_simulation(self, pin, monkeypatch):
        monkeypatch.setattr(sensor_module, "HAS_GPIO", True)
        s = make_sensor(pin=pin)
        assert s.gpio_available is False

    def test_bad_pin_still_starts_monitoring(self):
        s = make_sensor(pin=99)
        assert s.start_monitoring() is True
        assert s.is_monitoring is True

    @pytest.mark.parametrize("pin", [0, 18, 27])
    def test_boundary_pins_are_accepted(self, pin, monkeypatch):
        monkeypatch.setattr(sensor_module, "HAS_GPIO", True)
        assert make_sensor(pin=pin).gpio_available is True


class TestDebounce:
    """A PIR sensor retriggers constantly; only the first edge should count."""

    def test_first_motion_always_fires(self, clock, no_callbacks):
        callback = Mock()
        s = make_sensor(callback=callback)
        s._motion_detected()
        assert callback.call_count == 1

    def test_second_motion_inside_the_window_is_ignored(self, clock, no_callbacks):
        callback = Mock()
        s = make_sensor(callback=callback, **{"pir_sensor.debounce_time": 2.0})

        s._motion_detected()
        clock.advance(1.9)
        s._motion_detected()

        assert callback.call_count == 1

    def test_motion_after_the_window_fires_again(self, clock, no_callbacks):
        callback = Mock()
        s = make_sensor(callback=callback, **{"pir_sensor.debounce_time": 2.0})

        s._motion_detected()
        clock.advance(2.1)
        s._motion_detected()

        assert callback.call_count == 2

    def test_debounce_window_is_measured_from_the_accepted_event(
        self, clock, no_callbacks
    ):
        """Suppressed events must not extend the window (no starvation)."""
        callback = Mock()
        s = make_sensor(callback=callback, **{"pir_sensor.debounce_time": 2.0})

        s._motion_detected()
        for _ in range(3):
            clock.advance(0.5)
            s._motion_detected()
        assert callback.call_count == 1

        clock.advance(0.6)  # 2.1s after the accepted event
        s._motion_detected()
        assert callback.call_count == 2

    def test_suppressed_motion_does_not_reach_global_callbacks(
        self, clock, no_callbacks
    ):
        listener = Mock()
        add_motion_callback(listener)
        s = make_sensor(**{"pir_sensor.debounce_time": 2.0})

        s._motion_detected()
        clock.advance(0.1)
        s._motion_detected()

        assert listener.call_count == 1

    def test_last_detection_time_records_the_accepted_event(self, clock, no_callbacks):
        s = make_sensor()
        clock.now = 1234.5
        s._motion_detected()
        assert s.last_detection_time == 1234.5

    def test_zero_debounce_lets_every_event_through(self, clock, no_callbacks):
        callback = Mock()
        s = make_sensor(callback=callback, **{"pir_sensor.debounce_time": 0})
        s._motion_detected()
        s._motion_detected()
        assert callback.call_count == 2

    def test_failing_instance_callback_still_reaches_global_callbacks(
        self, clock, no_callbacks
    ):
        listener = Mock()
        add_motion_callback(listener)
        s = make_sensor(callback=Mock(side_effect=RuntimeError("boom")))

        s._motion_detected()

        assert listener.call_count == 1

    def test_motion_without_any_callback_is_harmless(self, clock, no_callbacks):
        s = make_sensor()
        s._motion_detected()
        assert s.last_detection_time == clock.now


class TestMotionCallbacks:
    """The global callback list is shared by every consumer of motion."""

    def test_callback_is_registered(self, no_callbacks):
        callback = Mock()
        add_motion_callback(callback)
        assert no_callbacks == [callback]

    def test_duplicate_registration_is_ignored(self, no_callbacks):
        callback = Mock()
        add_motion_callback(callback)
        add_motion_callback(callback)
        assert no_callbacks == [callback]

    def test_duplicate_registration_does_not_double_fire(self, no_callbacks):
        callback = Mock()
        add_motion_callback(callback)
        add_motion_callback(callback)
        trigger_motion_callbacks()
        assert callback.call_count == 1

    def test_distinct_callbacks_all_run(self, no_callbacks):
        first, second = Mock(), Mock()
        add_motion_callback(first)
        add_motion_callback(second)
        trigger_motion_callbacks()
        first.assert_called_once()
        second.assert_called_once()

    def test_a_raising_callback_does_not_block_the_others(self, no_callbacks):
        first = Mock(side_effect=RuntimeError("boom"))
        second = Mock()
        third = Mock()
        add_motion_callback(first)
        add_motion_callback(second)
        add_motion_callback(third)

        trigger_motion_callbacks()

        second.assert_called_once()
        third.assert_called_once()

    def test_trigger_with_no_callbacks_is_harmless(self, no_callbacks):
        trigger_motion_callbacks()


class TestMonitoringLifecycle:
    """start/stop/cleanup in simulation mode."""

    def test_start_monitoring_succeeds_in_simulation(self):
        s = make_sensor()
        assert s.start_monitoring() is True
        assert s.is_monitoring is True

    def test_start_monitoring_is_idempotent(self):
        s = make_sensor()
        s.setup = Mock(wraps=s.setup)

        assert s.start_monitoring() is True
        assert s.start_monitoring() is True

        assert s.setup.call_count == 1
        assert s.is_monitoring is True

    def test_start_monitoring_returns_false_when_setup_fails(self):
        s = make_sensor()
        s.setup = Mock(return_value=False)

        assert s.start_monitoring() is False
        assert s.is_monitoring is False

    def test_setup_is_a_noop_without_gpio(self):
        s = make_sensor()
        assert s.setup() is True
        assert s._sensor is None

    def test_stop_monitoring_clears_the_flag(self):
        s = make_sensor()
        s.start_monitoring()
        s.stop_monitoring()
        assert s.is_monitoring is False

    def test_stop_monitoring_before_start_is_harmless(self):
        s = make_sensor()
        s.stop_monitoring()
        assert s.is_monitoring is False

    def test_monitoring_can_be_restarted(self):
        s = make_sensor()
        s.start_monitoring()
        s.stop_monitoring()
        assert s.start_monitoring() is True
        assert s.is_monitoring is True

    def test_cleanup_stops_monitoring(self):
        s = make_sensor()
        s.start_monitoring()
        s.cleanup()
        assert s.is_monitoring is False

    def test_cleanup_without_a_gpio_handle_is_harmless(self):
        s = make_sensor()
        s.cleanup()
        assert s._sensor is None

    def test_cleanup_releases_and_drops_the_handle(self):
        """The only place a fake handle stands in for hardware."""
        s = make_sensor()
        handle = Mock()
        s._sensor = handle

        s.cleanup()

        handle.close.assert_called_once()
        assert s._sensor is None

    def test_cleanup_survives_a_failing_close(self):
        s = make_sensor()
        s._sensor = Mock(close=Mock(side_effect=RuntimeError("boom")))
        s.cleanup()  # must not raise


class TestGlobalSensor:
    """The module-level singleton and its helpers."""

    def test_initialize_sets_the_global_instance(self, no_shutdown_hooks):
        with stub_config():
            s = initialize_pir_sensor(pin=17)
        assert get_pir_sensor() is s
        assert s.pin == 17

    def test_reinitialising_releases_the_previous_sensor(self, no_shutdown_hooks):
        with stub_config():
            first = initialize_pir_sensor(pin=17)
        first.start_monitoring()

        with stub_config():
            second = initialize_pir_sensor(pin=18)

        assert second is not first
        assert first.is_monitoring is False
        assert get_pir_sensor() is second

    def test_helpers_are_noops_without_a_sensor(self):
        sensor_module._pir_sensor = None
        assert get_pir_sensor() is None
        assert start_pir_monitoring() is False
        stop_pir_monitoring()  # must not raise

    def test_helpers_delegate_to_the_global_sensor(self, no_shutdown_hooks):
        with stub_config():
            s = initialize_pir_sensor()

        assert start_pir_monitoring() is True
        assert s.is_monitoring is True

        stop_pir_monitoring()
        assert s.is_monitoring is False


class TestShutdownHooks:
    """Hooks are process-wide, so they must be installed exactly once."""

    def test_hooks_are_registered_on_first_initialize(self, no_shutdown_hooks):
        register, signal_signal = no_shutdown_hooks
        with stub_config():
            initialize_pir_sensor()

        register.assert_called_once_with(sensor_module._cleanup_on_exit)
        signal_signal.assert_called_once_with(
            sensor_module.signal.SIGTERM, sensor_module._signal_handler
        )

    def test_repeated_initialize_does_not_accumulate_hooks(self, no_shutdown_hooks):
        register, signal_signal = no_shutdown_hooks
        for _ in range(5):
            with stub_config():
                initialize_pir_sensor()

        assert register.call_count == 1
        assert signal_signal.call_count == 1

    def test_initialize_off_the_main_thread_still_returns_a_sensor(self):
        """signal.signal raises ValueError off the main thread; it must not escape."""
        sensor_module._atexit_registered = False
        sensor_module._sigterm_installed = False
        result = {}

        def run():
            try:
                with stub_config():
                    result["sensor"] = initialize_pir_sensor()
            except BaseException as e:  # pragma: no cover - failure path
                result["error"] = e

        with patch.object(sensor_module.atexit, "register"):
            thread = threading.Thread(target=run)
            thread.start()
            thread.join()

        assert "error" not in result
        assert isinstance(result["sensor"], PIRSensor)
        assert sensor_module._atexit_registered is True
        assert sensor_module._sigterm_installed is False

    def test_sigterm_hook_is_installed_by_a_later_main_thread_call(
        self, no_shutdown_hooks
    ):
        register, signal_signal = no_shutdown_hooks
        sensor_module._atexit_registered = True  # as if a worker thread got there first
        sensor_module._sigterm_installed = False

        with stub_config():
            initialize_pir_sensor()

        register.assert_not_called()
        signal_signal.assert_called_once()

    def test_cleanup_on_exit_releases_the_sensor(self, no_shutdown_hooks):
        with stub_config():
            s = initialize_pir_sensor()
        s.start_monitoring()

        sensor_module._cleanup_on_exit()

        assert s.is_monitoring is False

    def test_cleanup_on_exit_without_a_sensor_is_harmless(self):
        sensor_module._pir_sensor = None
        sensor_module._cleanup_on_exit()

    def test_signal_handler_cleans_up_then_exits(self, no_shutdown_hooks):
        with stub_config():
            s = initialize_pir_sensor()
        s.start_monitoring()

        with pytest.raises(SystemExit):
            sensor_module._signal_handler(sensor_module.signal.SIGTERM, None)

        assert s.is_monitoring is False
