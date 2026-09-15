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
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Pin gpiozero to the lgpio backend whenever lgpio is importable. Left to its
# own devices gpiozero tries lgpio, RPi.GPIO, pigpio and "native" in turn and,
# when all fail, raises a generic BadPinFactory that hides the real reason
# (a permission error on /dev/gpiochip0, say). With the factory fixed, the
# underlying exception surfaces in the log and on /pir/status.
try:
    import lgpio  # noqa: F401

    os.environ.setdefault("GPIOZERO_PIN_FACTORY", "lgpio")
    HAS_LGPIO = True
except ImportError:
    HAS_LGPIO = False

try:
    from gpiozero import MotionSensor

    HAS_GPIO = True
except ImportError:  # pragma: no cover - depends on the host
    MotionSensor = None  # type: ignore[assignment,misc]
    HAS_GPIO = False

# Valid BCM GPIO pin range on Raspberry Pi.
_VALID_GPIO_PINS = frozenset(range(0, 28))

# Kernel labels of the chip that drives the 40-pin header, by Pi generation.
# Chip *numbers* are not stable: a Raspberry Pi 5 on a 6.6 kernel exposes the
# header as /dev/gpiochip4, and on a 6.12 kernel as /dev/gpiochip10-15 with
# the RP1 header chip somewhere in that range. gpiozero's lgpio backend picks
# the number by board model and gets it wrong on the newer kernels, so the
# chip is located by label instead.
HEADER_CHIP_LABELS = (
    "pinctrl-rp1",  # Raspberry Pi 5
    "pinctrl-bcm2712",
    "pinctrl-bcm2711",  # Raspberry Pi 4
    "pinctrl-bcm2835",  # Pi 3 and earlier
    "pinctrl-bcm2837",
)


def list_gpio_chips() -> list[dict]:
    """Describe every /dev/gpiochip* the process can open, via lgpio."""
    import glob
    import re

    chips: list[dict] = []
    if not HAS_LGPIO:
        return chips
    for path in sorted(glob.glob("/dev/gpiochip*")):
        match = re.search(r"(\d+)$", path)
        if not match:
            continue
        number = int(match.group(1))
        entry: dict = {"number": number, "path": path}
        try:
            handle = lgpio.gpiochip_open(number)
            try:
                # lgpio returns [status, lines, name, label]; status < 0 is
                # an error code.
                info = list(lgpio.gpio_get_chip_info(handle))
            finally:
                lgpio.gpiochip_close(handle)
            if len(info) == 4:
                status, lines, name, label = info
                if status < 0:
                    raise RuntimeError(f"gpio_get_chip_info failed ({status})")
            else:  # pragma: no cover - older lgpio without the status field
                lines, name, label = info
            entry.update({"lines": int(lines), "name": name, "label": label})
        except Exception as e:
            entry["error"] = str(e)
        chips.append(entry)
    return chips


def detect_header_chip(chips: Optional[list[dict]] = None) -> Optional[int]:
    """The gpiochip number that carries the 40-pin header, or None."""
    if chips is None:
        chips = list_gpio_chips()
    for label in HEADER_CHIP_LABELS:
        for chip in chips:
            if str(chip.get("label", "")).startswith(label):
                return int(chip["number"])
    # Unknown board: the header chip is the one with the most lines, if it
    # has at least the 28 user GPIOs.
    candidates = [
        c for c in chips if isinstance(c.get("lines"), int) and c["lines"] >= 28
    ]
    if candidates:
        return int(max(candidates, key=lambda c: c["lines"])["number"])
    return None


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
        gpio_chip: Optional[int] = None,
    ):
        self.pin = pin
        self.debounce_seconds = float(debounce_seconds)
        self.simulation = bool(simulation)
        self.enabled = bool(enabled)
        # None = detect by label; an int pins it (pir_sensor.gpio_chip).
        self.gpio_chip = gpio_chip
        self.available = False
        self.error: Optional[str] = None
        self.pin_factory: Optional[str] = None
        self._factory = None
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
                kwargs: dict = {"queue_len": 1, "sample_rate": 10, "threshold": 0.5}
                factory = self._lgpio_factory()
                if factory is not None:
                    kwargs["pin_factory"] = factory
                sensor = MotionSensor(self.pin, **kwargs)
                sensor.when_motion = self._on_motion
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                if self.gpio_chip is not None:
                    self.error += f" [gpiochip {self.gpio_chip}]"
                if not HAS_LGPIO:
                    self.error += (
                        " [the lgpio Python module is not installed in this "
                        "environment, which a Raspberry Pi 5 requires: install "
                        "the swig and liblgpio-dev packages and re-run `uv sync`]"
                    )
                logger.error(
                    "PIR sensor: cannot open GPIO %s: %s. On a Raspberry Pi 5 the "
                    "service needs access to /dev/gpiochip* (see the systemd "
                    "unit) and the user must be in the 'gpio' group.",
                    self.pin,
                    self.error,
                )
                return False
            self._sensor = sensor
            self._factory = kwargs.get("pin_factory")
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

    def _lgpio_factory(self):
        """An lgpio pin factory on the header chip, or None to let gpiozero pick.

        Returns None when lgpio is not importable (another backend may still
        work, e.g. RPi.GPIO on a Pi 4) or when no chip could be identified;
        in the latter case gpiozero's own guess is the best remaining option.
        """
        if not HAS_LGPIO:
            return None
        chip = self.gpio_chip
        if chip is None:
            chip = detect_header_chip()
            if chip is None:
                logger.warning(
                    "PIR sensor: could not identify the header GPIO chip; "
                    "letting gpiozero choose"
                )
                return None
            self.gpio_chip = chip
        from gpiozero.pins.lgpio import LGPIOFactory

        logger.info("PIR sensor: using /dev/gpiochip%s via lgpio", chip)
        return LGPIOFactory(chip=chip)

    def close(self) -> None:
        with self._lock:
            sensor, self._sensor = self._sensor, None
            factory, self._factory = self._factory, None
            self.available = False
        if sensor is not None:
            try:
                sensor.when_motion = None
                sensor.close()
                logger.info("PIR sensor closed")
            except Exception:
                logger.exception("Error closing PIR sensor")
        if factory is not None:
            try:
                factory.close()
            except Exception:
                logger.debug("Error closing pin factory", exc_info=True)

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
            "lgpio_installed": HAS_LGPIO,
            "pin_factory_env": os.environ.get("GPIOZERO_PIN_FACTORY"),
            "gpio_chip": self.gpio_chip,
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
    chip = config.get("pir_sensor.gpio_chip")
    return PIRSensor(
        pin=config.get("pir_sensor.gpio_pin", 18),
        debounce_seconds=config.get("pir_sensor.debounce_time", 2.0),
        simulation=config.get("pir_sensor.simulation_mode", False),
        enabled=config.get("pir_sensor.enabled", True),
        gpio_chip=int(chip) if chip is not None else None,
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
