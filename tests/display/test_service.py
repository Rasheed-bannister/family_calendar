"""Tests for src/display/service.py."""

import datetime
import threading
from unittest.mock import Mock

import pytest

from src import events
from src.display import service as service_module
from src.display.backlight import Backlight, NullBacklight
from src.display.service import (
    DisplayService,
    build_service,
    ensure_display_service,
    get_display_service,
    set_display_service,
)
from src.display.state import (
    ACTIVE,
    DIMMED,
    SLIDESHOW,
    DisplayStateMachine,
    Schedule,
    Thresholds,
)

SCHEDULE = Schedule(
    day=Thresholds(10, 20, 0.6),
    night=Thresholds(1, 2, 0.2),
    night_start_hour=21,
    night_end_hour=6,
)


class Clocks:
    def __init__(self):
        self.mono = 0.0
        self.wall = datetime.datetime(2026, 9, 14, 12, 0)

    def monotonic(self):
        return self.mono

    def local_now(self):
        return self.wall

    def advance(self, seconds):
        self.mono += seconds
        self.wall += datetime.timedelta(seconds=seconds)


class RecordingBacklight(Backlight):
    name = "fake"

    def __init__(self, available=True):
        self._available = available
        self.levels = []

    @property
    def available(self):
        return self._available

    def set_brightness(self, level):
        self.levels.append(level)
        return self._available


@pytest.fixture(autouse=True)
def isolate_singleton():
    saved = get_display_service()
    set_display_service(None)
    yield
    set_display_service(saved)


def make_service(available=True, tick=1.0):
    clocks = Clocks()
    machine = DisplayStateMachine(
        SCHEDULE, clock=clocks.monotonic, local_now=clocks.local_now
    )
    backlight = RecordingBacklight(available)
    publish = Mock(return_value=1)
    service = DisplayService(
        machine, backlight=backlight, publish=publish, tick_seconds=tick
    )
    return service, clocks, backlight, publish


class TestTickAndActivity:
    def test_tick_applies_mode_changes_to_backlight_and_broker(self):
        service, clocks, backlight, publish = make_service()
        assert service.tick() is False
        publish.assert_not_called()

        clocks.advance(10)
        assert service.tick() is True
        assert backlight.levels == [0.6]
        publish.assert_called_once()
        event_type, kwargs = publish.call_args[0][0], publish.call_args[1]
        assert event_type == events.DISPLAY_CHANGED
        assert kwargs["mode"] == DIMMED
        assert kwargs["overlay_brightness"] == 1.0  # hardware did the dimming

        clocks.advance(10)
        assert service.tick() is True
        assert publish.call_args[1]["mode"] == SLIDESHOW

    def test_activity_wakes_and_returns_snapshot(self):
        service, clocks, backlight, publish = make_service()
        clocks.advance(30)
        service.tick()
        snap = service.activity("touch")
        assert snap["mode"] == ACTIVE
        assert snap["last_activity_source"] == "touch"
        assert backlight.levels[-1] == 1.0
        assert publish.call_args[1]["mode"] == ACTIVE

    def test_activity_without_change_publishes_nothing(self):
        service, _, backlight, publish = make_service()
        service.activity("pir")
        publish.assert_not_called()
        assert backlight.levels == []

    def test_force_slideshow(self):
        service, _, _, publish = make_service()
        snap = service.force_slideshow()
        assert snap["mode"] == SLIDESHOW
        assert publish.call_args[1]["mode"] == SLIDESHOW

    def test_overlay_brightness_when_no_hardware(self):
        service, clocks, _, _ = make_service(available=False)
        clocks.advance(10)
        service.tick()
        snap = service.snapshot()
        assert snap["brightness"] == 0.6
        assert snap["overlay_brightness"] == 0.6

    def test_overlay_brightness_is_floored_without_hardware(self):
        # Night brightness 0.2 would be an 80% black overlay; the fallback
        # never goes below the floor.
        clocks = Clocks()
        clocks.wall = datetime.datetime(2026, 9, 14, 23, 0)
        machine = DisplayStateMachine(
            SCHEDULE, clock=clocks.monotonic, local_now=clocks.local_now
        )
        service = DisplayService(
            machine, backlight=NullBacklight(), publish=Mock(return_value=1)
        )
        clocks.advance(5)
        service.tick()
        snap = service.snapshot()
        assert snap["brightness"] == 0.2
        assert snap["overlay_brightness"] == 0.35

        floored = DisplayService(
            machine,
            backlight=NullBacklight(),
            publish=Mock(return_value=1),
            overlay_min_brightness=0.5,
        )
        assert floored.snapshot()["overlay_brightness"] == 0.5

    def test_listeners_receive_snapshots_and_failures_are_contained(self, caplog):
        service, clocks, _, _ = make_service()
        seen = []
        service.on_change(lambda snap: seen.append(snap["mode"]))
        service.on_change(Mock(side_effect=RuntimeError("boom")))
        clocks.advance(10)
        with caplog.at_level("ERROR"):
            service.tick()
        assert seen == [DIMMED]
        assert "Display listener failed" in caplog.text

    def test_publish_failure_is_contained(self):
        service, clocks, _, publish = make_service()
        publish.side_effect = RuntimeError("broker down")
        clocks.advance(10)
        assert service.tick() is True


class TestLifecycle:
    def test_start_applies_initial_state_and_runs_ticker(self):
        service, clocks, backlight, publish = make_service(tick=0.05)
        service.start()
        try:
            assert service.running is True
            assert backlight.levels[0] == 1.0
            publish.assert_called_once()
            clocks.advance(10)
            deadline = threading.Event()
            for _ in range(40):
                if publish.call_count >= 2:
                    break
                deadline.wait(0.05)
            assert publish.call_args[1]["mode"] == DIMMED
        finally:
            service.stop()
        assert service.running is False
        assert backlight.levels[-1] == 1.0  # screen left usable

    def test_start_is_idempotent(self):
        service, _, _, _ = make_service(tick=0.05)
        service.start()
        first = service._thread
        service.start()
        try:
            assert service._thread is first
        finally:
            service.stop()

    def test_tick_survives_an_evaluate_error(self, caplog):
        service, clocks, _, _ = make_service(tick=0.02)
        service._machine.evaluate = Mock(side_effect=RuntimeError("bad"))
        service.start()
        try:
            threading.Event().wait(0.1)
            assert service.running is True
        finally:
            service._machine.evaluate = Mock(return_value=False)
            service.stop()


class TestSingleton:
    def test_ensure_builds_once(self):
        class Cfg:
            def get(self, key, default=None):
                return {"display.backlight.backend": "none"}.get(key, default)

        first = ensure_display_service(Cfg())
        second = ensure_display_service(Cfg())
        assert first is second
        assert get_display_service() is first
        assert first.running is False  # ensure() never starts the ticker

    def test_build_service_uses_configured_backlight_and_timezone(self):
        class Cfg:
            def get(self, key, default=None):
                return {
                    "display.backlight.backend": "none",
                    "display.tick_seconds": 0.5,
                }.get(key, default)

        service = build_service(Cfg())
        assert isinstance(service._backlight, NullBacklight)
        assert service._tick == 0.5
        assert service.snapshot()["mode"] == ACTIVE

    def test_set_and_get(self):
        marker = object()
        set_display_service(marker)
        assert get_display_service() is marker
        assert service_module._service is marker
