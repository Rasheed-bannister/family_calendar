"""Tests for the display state machine (src/display/state.py).

Driven entirely with a fake monotonic clock and a fake wall clock, so a
60-minute day timeout costs nothing to test.
"""

import datetime

import pytest

from src.display.state import (
    ACTIVE,
    DIMMED,
    SLIDESHOW,
    DisplayStateMachine,
    Schedule,
    Thresholds,
)

DAY = Thresholds(dim_after_seconds=60, hide_ui_after_seconds=90, brightness=0.6)
NIGHT = Thresholds(dim_after_seconds=5, hide_ui_after_seconds=10, brightness=0.2)
SCHEDULE = Schedule(day=DAY, night=NIGHT, night_start_hour=21, night_end_hour=6)


class Clocks:
    def __init__(self, hour=12):
        self.mono = 1000.0
        self.wall = datetime.datetime(2026, 9, 14, hour, 0, 0)

    def monotonic(self):
        return self.mono

    def local_now(self):
        return self.wall

    def advance(self, seconds):
        self.mono += seconds
        self.wall += datetime.timedelta(seconds=seconds)


def machine(hour=12):
    clocks = Clocks(hour)
    return (
        DisplayStateMachine(
            SCHEDULE, clock=clocks.monotonic, local_now=clocks.local_now
        ),
        clocks,
    )


class TestThresholds:
    def test_hide_is_clamped_up_to_dim(self):
        t = Thresholds(dim_after_seconds=30, hide_ui_after_seconds=10, brightness=0.5)
        assert t.hide_ui_after_seconds == 30

    def test_negative_and_out_of_range_values_are_clamped(self):
        t = Thresholds(dim_after_seconds=-5, hide_ui_after_seconds=-1, brightness=7)
        assert (t.dim_after_seconds, t.hide_ui_after_seconds, t.brightness) == (
            0.0,
            0.0,
            1.0,
        )


class TestSchedule:
    @pytest.mark.parametrize(
        "hour,expected",
        [
            (20, False),
            (21, True),
            (23, True),
            (0, True),
            (5, True),
            (6, False),
            (12, False),
        ],
    )
    def test_night_window_wrapping_midnight(self, hour, expected):
        when = datetime.datetime(2026, 1, 1, hour)
        assert SCHEDULE.is_night(when) is expected

    def test_night_window_not_wrapping(self):
        schedule = Schedule(day=DAY, night=NIGHT, night_start_hour=1, night_end_hour=5)
        assert schedule.is_night(datetime.datetime(2026, 1, 1, 3)) is True
        assert schedule.is_night(datetime.datetime(2026, 1, 1, 5)) is False
        assert schedule.is_night(datetime.datetime(2026, 1, 1, 23)) is False

    def test_equal_hours_mean_never_night(self):
        schedule = Schedule(day=DAY, night=NIGHT, night_start_hour=6, night_end_hour=6)
        assert schedule.is_night(datetime.datetime(2026, 1, 1, 6)) is False

    def test_thresholds_at(self):
        assert SCHEDULE.thresholds_at(datetime.datetime(2026, 1, 1, 12)) is DAY
        assert SCHEDULE.thresholds_at(datetime.datetime(2026, 1, 1, 22)) is NIGHT

    def test_from_config(self):
        class Cfg:
            values = {
                "display.day.dim_after_seconds": 100,
                "display.day.hide_ui_after_seconds": 200,
                "display.day.brightness": 0.7,
                "display.night.dim_after_seconds": 3,
                "display.night.hide_ui_after_seconds": 4,
                "display.night.brightness": 0.1,
                "display.night_start_hour": 22,
                "display.night_end_hour": 7,
            }

            def get(self, key, default=None):
                return self.values.get(key, default)

        schedule = Schedule.from_config(Cfg())
        assert schedule.day == Thresholds(100, 200, 0.7)
        assert schedule.night == Thresholds(3, 4, 0.1)
        assert (schedule.night_start_hour, schedule.night_end_hour) == (22, 7)

    def test_from_config_defaults(self):
        class Empty:
            def get(self, key, default=None):
                return default

        schedule = Schedule.from_config(Empty())
        assert schedule.day.dim_after_seconds == 3600
        assert schedule.night.hide_ui_after_seconds == 10


class TestTransitions:
    def test_starts_active(self):
        m, _ = machine()
        assert m.mode == ACTIVE
        assert m.brightness == 1.0
        assert m.evaluate() is False

    def test_day_dims_then_hides(self):
        m, clocks = machine(hour=12)
        clocks.advance(59)
        assert m.evaluate() is False
        clocks.advance(1)
        assert m.evaluate() is True
        assert m.mode == DIMMED
        assert m.brightness == 0.6
        clocks.advance(29)
        assert m.evaluate() is False
        clocks.advance(1)
        assert m.evaluate() is True
        assert m.mode == SLIDESHOW

    def test_night_uses_the_night_thresholds(self):
        """The old code gated hiding on the *day* timeout even at night."""
        m, clocks = machine(hour=23)
        clocks.advance(5)
        assert m.evaluate() is True
        assert m.mode == DIMMED
        assert m.brightness == 0.2
        clocks.advance(5)
        assert m.evaluate() is True
        assert m.mode == SLIDESHOW

    def test_activity_wakes_and_resets_the_clock(self):
        m, clocks = machine()
        clocks.advance(100)
        m.evaluate()
        assert m.mode == SLIDESHOW
        assert m.activity("touch") is True
        assert m.mode == ACTIVE
        assert m.idle_seconds == 0
        clocks.advance(59)
        assert m.evaluate() is False
        assert m.mode == ACTIVE

    def test_activity_while_active_changes_nothing(self):
        m, _ = machine()
        assert m.activity("pir") is False
        assert m.snapshot()["last_activity_source"] == "pir"

    def test_evaluate_is_idempotent(self):
        m, clocks = machine()
        clocks.advance(1000)
        assert m.evaluate() is True
        assert m.evaluate() is False

    def test_crossing_into_night_re_evaluates_with_night_thresholds(self):
        m, clocks = machine(hour=20)
        clocks.wall = clocks.wall.replace(minute=59, second=57)
        clocks.advance(2)  # 20:59:59, 2s idle: nothing under the day rules
        assert m.evaluate() is False
        clocks.advance(4)  # 21:00:03, 6s idle: past the 5s night dim threshold
        assert m.evaluate() is True
        assert m.mode == DIMMED
        assert m.is_night is True
        assert m.brightness == 0.2

    def test_force_slideshow_sticks_until_activity(self):
        m, clocks = machine()
        assert m.force_slideshow() is True
        assert m.mode == SLIDESHOW
        assert m.evaluate() is False  # not re-derived from idle time
        clocks.advance(1)
        assert m.evaluate() is False
        assert m.activity("touch") is True
        assert m.mode == ACTIVE

    def test_snapshot_shape(self):
        m, clocks = machine(hour=12)
        m.activity("keyboard")
        clocks.advance(70)
        m.evaluate()
        snap = m.snapshot()
        assert snap["mode"] == DIMMED
        assert snap["brightness"] == 0.6
        assert snap["is_night"] is False
        assert snap["idle_seconds"] == 70.0
        assert snap["last_activity_source"] == "keyboard"
        assert snap["last_activity_at"] == "2026-09-14T12:00:00"
        assert snap["thresholds"] == {
            "dim_after_seconds": 60.0,
            "hide_ui_after_seconds": 90.0,
            "brightness": 0.6,
        }
