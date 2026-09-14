"""PIR motion sensor.

One sensor object per process, opened once at startup by :mod:`src.runtime`
and closed at exit. There is deliberately no start/stop over HTTP: the old
design let the browser stop and restart the sensor on every page load, and
the restart re-opened a GPIO pin the previous object still held, which
gpiozero refuses -- after which the code fell back to "simulation mode"
while reporting that it was monitoring. Motion never worked again until the
process was restarted.

Failure is loud. If the sensor is enabled, not in simulation mode, and cannot
be opened, that is an ERROR in the log, an ``error`` string on
``/pir/status``, a failed check on ``/health/``, and a badge on screen.

Uses gpiozero, which is what works on a Raspberry Pi 5 (via lgpio).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    from gpiozero import MotionSensor

    HAS_GPIO = True
except ImportError:  # pragma: no cover - depends on the host
    MotionSensor = None  # type: ignore[assignment,misc]
    HAS_GPIO = False

# Valid BCM GPIO pin range on Raspberry Pi.
_VALID_GPIO_PINS = frozenset(range(0, 28))

# Process-wide listeners, called on every debounced motion event.
_motion_callbacks: list[Callable[[], None]] = []
_callbacks_lock = threading.Lock()


def add_motion_callback(callback: Callable[[], None]) -> None:
    with _callbacks_lock:
        if callback not in _motion_callbacks:
            _motion_callbacks.append(callback)


def remove_motion_callback(callback: Callable[[], None]) -> None:
    with _callbacks_lock:
        try:
            _motion_callbacks.remove(callback)
        except ValueError:
            pass


def trigger_motion_callbacks() -> None:
    with _callbacks_lock:
        callbacks = list(_motion_callbacks)
    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.exception("Error in motion callback")


class PIRSensor:
    """A single PIR sensor on one GPIO pin."""

    def __init__(
        self,
        pin: int = 18,
        debounce_seconds: float = 2.0,
        simulation: bool = False,
        enabled: bool = True,
    ):
        self.pin = pin
        self.debounce_seconds = float(debounce_seconds)
        self.simulation = bool(simulation)
        self.enabled = bool(enabled)
        self.available = False
        self.error: Optional[str] = None
        self.pin_factory: Optional[str] = None
        self.last_motion_at: Optional[float] = None
        self.motion_count = 0
        self._sensor = None
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------

    def open(self) -> bool:
        """Claim the GPIO pin. Returns True when real hardware is live.

        In simulation mode, or when the sensor is disabled, this succeeds
        without touching hardware and ``available`` stays False.
        """
        with self._lock:
            if self._sensor is not None:
                return True
            if not self.enabled:
                logger.info("PIR sensor disabled by configuration")
                return False
            if self.simulation:
                logger.warning(
                    "PIR sensor in simulation mode (pir_sensor.simulation_mode=true); "
                    "motion will only come from the test endpoint"
                )
                return False
            if not isinstance(self.pin, int) or self.pin not in _VALID_GPIO_PINS:
                self.error = f"Invalid GPIO pin {self.pin!r} (must be 0-27)"
                logger.error("PIR sensor: %s", self.error)
                return False
            if not HAS_GPIO:
                self.error = (
                    "gpiozero is not installed; install gpiozero and lgpio "
                    "(and the swig/liblgpio-dev system packages)"
                )
                logger.error("PIR sensor: %s", self.error)
                return False
            try:
                sensor = MotionSensor(
                    self.pin, queue_len=1, sample_rate=10, threshold=0.5
                )
                sensor.when_motion = self._on_motion
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                logger.error(
                    "PIR sensor: cannot open GPIO %s: %s. On a Raspberry Pi 5 the "
                    "service needs access to /dev/gpiochip* (see the systemd "
                    "unit) and the user must be in the 'gpio' group.",
                    self.pin,
                    self.error,
                )
                return False
            self._sensor = sensor
            self.available = True
            self.error = None
            try:
                self.pin_factory = type(sensor.pin_factory).__name__
            except Exception:  # pragma: no cover - cosmetic
                self.pin_factory = None
            logger.info(
                "PIR sensor open on GPIO %s (pin factory %s)",
                self.pin,
                self.pin_factory,
            )
            return True

    def close(self) -> None:
        with self._lock:
            sensor, self._sensor = self._sensor, None
            self.available = False
        if sensor is not None:
            try:
                sensor.when_motion = None
                sensor.close()
                logger.info("PIR sensor closed")
            except Exception:
                logger.exception("Error closing PIR sensor")

    # -- events ---------------------------------------------------------

    def _on_motion(self) -> None:
        now = time.monotonic()
        if (
            self.last_motion_at is not None
            and now - self.last_motion_at < self.debounce_seconds
        ):
            return
        self.last_motion_at = now
        self.motion_count += 1
        logger.debug("PIR motion (#%d)", self.motion_count)
        trigger_motion_callbacks()

    def simulate_motion(self) -> None:
        """Feed a fake motion event through the same path as real ones."""
        self._on_motion()

    # -- reporting ------------------------------------------------------

    def status(self) -> dict:
        seconds_since = (
            None
            if self.last_motion_at is None
            else round(time.monotonic() - self.last_motion_at, 1)
        )
        return {
            "enabled": self.enabled,
            "simulation": self.simulation,
            "available": self.available,
            "pin": self.pin,
            "pin_factory": self.pin_factory,
            "error": self.error,
            "gpiozero_installed": HAS_GPIO,
            "motion_count": self.motion_count,
            "seconds_since_motion": seconds_since,
        }

    @property
    def healthy(self) -> bool:
        """False only when hardware was expected and is not working."""
        if not self.enabled or self.simulation:
            return True
        return self.available


# --- process-wide singleton -------------------------------------------------

_pir_sensor: Optional[PIRSensor] = None
_init_lock = threading.Lock()


def build_sensor(config) -> PIRSensor:
    return PIRSensor(
        pin=config.get("pir_sensor.gpio_pin", 18),
        debounce_seconds=config.get("pir_sensor.debounce_time", 2.0),
        simulation=config.get("pir_sensor.simulation_mode", False),
        enabled=config.get("pir_sensor.enabled", True),
    )


def initialize_pir_sensor(config=None) -> PIRSensor:
    """Create (or replace) the process-wide sensor and open it."""
    global _pir_sensor
    if config is None:
        from src.config import get_config

        config = get_config()
    with _init_lock:
        if _pir_sensor is not None:
            _pir_sensor.close()
        _pir_sensor = build_sensor(config)
        _pir_sensor.open()
        return _pir_sensor


def get_pir_sensor() -> Optional[PIRSensor]:
    return _pir_sensor


def set_pir_sensor(sensor: Optional[PIRSensor]) -> None:
    """Install a sensor object directly (tests use this to inject a fake)."""
    global _pir_sensor
    with _init_lock:
        _pir_sensor = sensor


def shutdown_pir_sensor() -> None:
    global _pir_sensor
    with _init_lock:
        sensor, _pir_sensor = _pir_sensor, None
    if sensor is not None:
        sensor.close()
