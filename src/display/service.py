"""Runs the display state machine and pushes its decisions outward.

One instance per process. It owns a 1 Hz ticker thread that re-evaluates
the mode, and it is the only thing that touches the backlight or publishes
``display_changed`` events. Activity arrives from two places: the PIR
sensor callback (see :mod:`src.runtime`) and ``POST /api/display/activity``
(see :mod:`src.display.routes`).
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Callable, Optional

from src import events
from src.events import broker

from .backlight import Backlight, NullBacklight, create_backlight
from .state import DisplayStateMachine, Schedule

logger = logging.getLogger(__name__)


class DisplayService:
    def __init__(
        self,
        machine: DisplayStateMachine,
        backlight: Optional[Backlight] = None,
        publish: Optional[Callable[..., int]] = None,
        tick_seconds: float = 1.0,
    ):
        self._machine = machine
        self._backlight = backlight or NullBacklight()
        self._publish = publish or broker.publish
        self._tick = max(0.1, float(tick_seconds))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: list[Callable[[dict], None]] = []

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="display-service", daemon=True
            )
            self._thread.start()
        # Put the hardware in a known state immediately.
        self._apply()
        logger.info(
            "Display service started (backlight=%s)", self._backlight.describe()
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout)
        # Leave the screen usable when the service goes away.
        self._backlight.set_brightness(1.0)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.wait(self._tick):
            try:
                self.tick()
            except Exception:  # pragma: no cover - keep the ticker alive
                logger.exception("Display tick failed")

    # -- inputs ---------------------------------------------------------

    def tick(self) -> bool:
        """Re-evaluate once. Returns True if the mode changed."""
        with self._lock:
            changed = self._machine.evaluate()
            if changed:
                self._apply()
            return changed

    def activity(self, source: str) -> dict:
        """Record activity and return the resulting snapshot."""
        with self._lock:
            changed = self._machine.activity(source)
            if changed:
                self._apply()
            return self.snapshot()

    def force_slideshow(self) -> dict:
        with self._lock:
            if self._machine.force_slideshow():
                self._apply()
            return self.snapshot()

    def on_change(self, listener: Callable[[dict], None]) -> None:
        """Register an in-process listener called with each new snapshot."""
        self._listeners.append(listener)

    # -- outputs --------------------------------------------------------

    def snapshot(self) -> dict:
        snap = self._machine.snapshot()
        hardware = self._backlight.available
        # The browser only dims with CSS when there is no hardware backlight;
        # otherwise it would dim twice.
        snap["overlay_brightness"] = 1.0 if hardware else snap["brightness"]
        snap["backlight"] = self._backlight.describe()
        return snap

    def _apply(self) -> None:
        snap = self.snapshot()
        self._backlight.set_brightness(snap["brightness"])
        logger.info(
            "Display mode -> %s (brightness %.2f, night=%s, source=%s)",
            snap["mode"],
            snap["brightness"],
            snap["is_night"],
            snap["last_activity_source"],
        )
        try:
            self._publish(events.DISPLAY_CHANGED, **snap)
        except Exception:  # pragma: no cover - publish never raises by contract
            logger.exception("Could not publish display change")
        for listener in list(self._listeners):
            try:
                listener(snap)
            except Exception:
                logger.exception("Display listener failed")


# --- process-wide singleton -------------------------------------------------

_service: Optional[DisplayService] = None
_service_lock = threading.Lock()


def build_service(config) -> DisplayService:
    """Construct a service from configuration (does not start it)."""
    from src.config import get_local_timezone

    tz = get_local_timezone()
    machine = DisplayStateMachine(
        Schedule.from_config(config),
        local_now=lambda: datetime.datetime.now(tz=tz),
    )
    return DisplayService(
        machine,
        backlight=create_backlight(config),
        tick_seconds=config.get("display.tick_seconds", 1.0),
    )


def get_display_service() -> Optional[DisplayService]:
    return _service


def set_display_service(service: Optional[DisplayService]) -> None:
    """Install the process-wide service (tests use this to inject a fake)."""
    global _service
    with _service_lock:
        _service = service


def ensure_display_service(config) -> DisplayService:
    """Return the singleton, building it on first use."""
    global _service
    with _service_lock:
        if _service is None:
            _service = build_service(config)
        return _service
