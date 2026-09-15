"""The display state machine, as a plain class with an injectable clock.

No threads, no Flask, no hardware: everything here is deterministic given
the inputs, which is what makes the transitions testable with a fake clock.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Callable, Optional

ACTIVE = "active"
DIMMED = "dimmed"
SLIDESHOW = "slideshow"

MODES = (ACTIVE, DIMMED, SLIDESHOW)


@dataclass(frozen=True)
class Thresholds:
    """Idle thresholds and target brightness for one part of the day.

    ``dim_after_seconds``: idle time before the screen dims.
    ``hide_ui_after_seconds``: idle time before the UI hides and only the
    slideshow remains. Must be >= ``dim_after_seconds``; it is clamped up if
    not, so a misconfiguration degrades to "dim and hide at the same time"
    rather than to a mode that can never be reached.
    ``brightness``: backlight level (0..1) while not active.
    """

    dim_after_seconds: float
    hide_ui_after_seconds: float
    brightness: float

    def __post_init__(self):
        dim = max(0.0, float(self.dim_after_seconds))
        hide = max(dim, float(self.hide_ui_after_seconds))
        level = min(1.0, max(0.0, float(self.brightness)))
        object.__setattr__(self, "dim_after_seconds", dim)
        object.__setattr__(self, "hide_ui_after_seconds", hide)
        object.__setattr__(self, "brightness", level)


@dataclass(frozen=True)
class Schedule:
    """Day and night thresholds plus the hours that separate them."""

    day: Thresholds
    night: Thresholds
    night_start_hour: int = 21
    night_end_hour: int = 6

    def is_night(self, local_time: datetime.datetime) -> bool:
        """Whether ``local_time`` falls inside the night window.

        The window may wrap midnight (21 -> 6) or not (0 -> 6). Equal start
        and end hours mean "never night".
        """
        hour = local_time.hour
        start, end = self.night_start_hour, self.night_end_hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def thresholds_at(self, local_time: datetime.datetime) -> Thresholds:
        return self.night if self.is_night(local_time) else self.day

    @classmethod
    def from_config(cls, config) -> "Schedule":
        """Build a schedule from the ``display`` config section."""

        def thresholds(section: str, defaults: tuple) -> Thresholds:
            return Thresholds(
                dim_after_seconds=config.get(
                    f"display.{section}.dim_after_seconds", defaults[0]
                ),
                hide_ui_after_seconds=config.get(
                    f"display.{section}.hide_ui_after_seconds", defaults[1]
                ),
                brightness=config.get(f"display.{section}.brightness", defaults[2]),
            )

        return cls(
            day=thresholds("day", (3600, 3605, 0.6)),
            night=thresholds("night", (5, 10, 0.2)),
            night_start_hour=int(config.get("display.night_start_hour", 21)),
            night_end_hour=int(config.get("display.night_end_hour", 6)),
        )


class DisplayStateMachine:
    """Decides the display mode from idle time and time of day.

    ``clock`` is a monotonic seconds source (for idle time) and ``local_now``
    yields the wall-clock time in the display's timezone (for day/night).
    Both are injectable so tests never sleep.
    """

    def __init__(
        self,
        schedule: Schedule,
        clock: Callable[[], float] = time.monotonic,
        local_now: Optional[Callable[[], datetime.datetime]] = None,
    ):
        self._schedule = schedule
        self._clock = clock
        self._local_now = local_now or datetime.datetime.now
        self._last_activity = clock()
        self._last_source: Optional[str] = None
        self._last_activity_wall: Optional[datetime.datetime] = None
        self._mode = ACTIVE
        self._forced_slideshow = False

    # -- inputs ---------------------------------------------------------

    def activity(self, source: str) -> bool:
        """Record real activity. Returns True if the mode changed."""
        self._last_activity = self._clock()
        self._last_source = source
        self._last_activity_wall = self._local_now()
        self._forced_slideshow = False
        return self._set_mode(ACTIVE)

    def force_slideshow(self) -> bool:
        """Jump straight to the slideshow, until the next activity."""
        self._forced_slideshow = True
        return self._set_mode(SLIDESHOW)

    def evaluate(self) -> bool:
        """Re-derive the mode from the clock. Returns True if it changed."""
        if self._forced_slideshow:
            return self._set_mode(SLIDESHOW)
        thresholds = self.thresholds
        idle = self.idle_seconds
        if idle >= thresholds.hide_ui_after_seconds:
            target = SLIDESHOW
        elif idle >= thresholds.dim_after_seconds:
            target = DIMMED
        else:
            target = ACTIVE
        return self._set_mode(target)

    def _set_mode(self, mode: str) -> bool:
        if mode == self._mode:
            return False
        self._mode = mode
        return True

    # -- outputs --------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def idle_seconds(self) -> float:
        return max(0.0, self._clock() - self._last_activity)

    @property
    def is_night(self) -> bool:
        return self._schedule.is_night(self._local_now())

    @property
    def thresholds(self) -> Thresholds:
        return self._schedule.thresholds_at(self._local_now())

    @property
    def brightness(self) -> float:
        """Target backlight level for the current mode."""
        if self._mode == ACTIVE:
            return 1.0
        return self.thresholds.brightness

    def snapshot(self) -> dict:
        """JSON-friendly view of the state, as sent to the browser."""
        thresholds = self.thresholds
        return {
            "mode": self._mode,
            "brightness": self.brightness,
            "is_night": self.is_night,
            "idle_seconds": round(self.idle_seconds, 1),
            "last_activity_source": self._last_source,
            "last_activity_at": (
                self._last_activity_wall.isoformat()
                if self._last_activity_wall
                else None
            ),
            "thresholds": {
                "dim_after_seconds": thresholds.dim_after_seconds,
                "hide_ui_after_seconds": thresholds.hide_ui_after_seconds,
                "brightness": thresholds.brightness,
            },
        }
