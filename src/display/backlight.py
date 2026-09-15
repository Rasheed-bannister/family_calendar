"""Backlight control.

Dimming used to be a translucent black ``<div>`` over the page. That neither
saved power nor looked right, because it sat above the photos it was meant
to sit under. Here the server drives the real backlight where one exists and
tells the browser whether it still needs a CSS fallback.

Backends
--------
``sysfs``   The official Raspberry Pi touchscreen and most panel backlights
            expose ``/sys/class/backlight/<name>/brightness``. Writing needs
            the ``video`` group plus a udev rule (installed by the deploy
            script) that makes the file group-writable.
``ddcutil`` HDMI monitors that support DDC/CI. Slow (hundreds of ms per
            call) and occasionally flaky, so calls are serialised and never
            block the caller.
``none``    No hardware control; the browser dims with an overlay.

``auto`` picks sysfs if a device exists, then ddcutil if the binary exists,
else none.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404 - ddcutil is invoked with a fixed argv
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SYSFS_ROOT = Path("/sys/class/backlight")


class Backlight:
    """Interface every backend implements."""

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def set_brightness(self, level: float) -> bool:
        """Set the backlight to ``level`` in 0..1. Returns True on success."""
        return False

    def describe(self) -> dict:
        return {"backend": self.name, "available": self.available}


class NullBacklight(Backlight):
    """No hardware control. The browser applies a CSS overlay instead."""

    def set_brightness(self, level: float) -> bool:
        return False


class SysfsBacklight(Backlight):
    name = "sysfs"

    def __init__(self, device_dir: Path, minimum_fraction: float = 0.02):
        self._dir = device_dir
        self._max = self._read_int("max_brightness") or 0
        # Never write 0: on some panels that switches the backlight off
        # entirely, and a screen nobody can see is not "dimmed".
        self._floor = max(1, int(round(self._max * minimum_fraction)))
        self._last_error: Optional[str] = None

    def _read_int(self, name: str) -> Optional[int]:
        try:
            return int((self._dir / name).read_text().strip())
        except (OSError, ValueError) as e:
            self._last_error = str(e)
            return None

    @property
    def available(self) -> bool:
        return self._max > 0 and (self._dir / "brightness").exists()

    def set_brightness(self, level: float) -> bool:
        if not self.available:
            return False
        level = min(1.0, max(0.0, level))
        raw = max(self._floor, int(round(self._max * level)))
        try:
            (self._dir / "brightness").write_text(f"{raw}\n")
            self._last_error = None
            return True
        except OSError as e:
            # Log once per distinct failure, not once per tick.
            if str(e) != self._last_error:
                logger.error(
                    "Cannot write backlight %s: %s (is the service in the "
                    "'video' group and is the udev rule installed?)",
                    self._dir,
                    e,
                )
            self._last_error = str(e)
            return False

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available,
            "device": str(self._dir),
            "max_brightness": self._max,
            "error": self._last_error,
        }


class DdcutilBacklight(Backlight):
    name = "ddcutil"

    def __init__(self, binary: str = "ddcutil", display: Optional[str] = None):
        self._binary = binary
        self._display = display
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None
        self._pending: Optional[int] = None

    @property
    def available(self) -> bool:
        return shutil.which(self._binary) is not None

    def set_brightness(self, level: float) -> bool:
        if not self.available:
            return False
        percent = int(round(min(1.0, max(0.0, level)) * 100))
        # ddcutil takes ~0.5s; run it off the caller's thread and collapse
        # bursts to the most recent value.
        with self._lock:
            first = self._pending is None
            self._pending = percent
        if first:
            threading.Thread(
                target=self._drain, name="ddcutil-backlight", daemon=True
            ).start()
        return True

    def _drain(self) -> None:
        while True:
            with self._lock:
                percent = self._pending
                if percent is None:
                    return
                self._pending = None
            argv = [self._binary, "setvcp", "10", str(percent), "--noverify"]
            if self._display:
                argv += ["--display", str(self._display)]
            try:
                subprocess.run(  # nosec B603 - fixed argv, no shell
                    argv, check=True, capture_output=True, timeout=10
                )
                self._last_error = None
            except (subprocess.SubprocessError, OSError) as e:
                msg = str(e)
                if msg != self._last_error:
                    logger.error("ddcutil failed: %s", msg)
                self._last_error = msg
            with self._lock:
                if self._pending is None:
                    return

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "available": self.available,
            "display": self._display,
            "error": self._last_error,
        }


def _first_sysfs_device(preferred: Optional[str] = None) -> Optional[Path]:
    if preferred:
        candidate = SYSFS_ROOT / preferred
        return candidate if candidate.is_dir() else None
    if not SYSFS_ROOT.is_dir():
        return None
    devices = sorted(p for p in SYSFS_ROOT.iterdir() if p.is_dir())
    return devices[0] if devices else None


def create_backlight(config) -> Backlight:
    """Instantiate the configured backend (``display.backlight.*``)."""
    backend = str(config.get("display.backlight.backend", "auto") or "auto").lower()
    device = config.get("display.backlight.device")

    if backend in ("auto", "sysfs"):
        path = _first_sysfs_device(device if backend == "sysfs" else None)
        if path is not None:
            candidate = SysfsBacklight(path)
            if candidate.available:
                logger.info("Backlight: sysfs device %s", path)
                return candidate
            logger.warning("Backlight device %s exists but is unusable", path)
        if backend == "sysfs":
            logger.error("Backlight backend 'sysfs' configured but no device found")
            return NullBacklight()

    if backend in ("auto", "ddcutil"):
        ddc = DdcutilBacklight(display=device if backend == "ddcutil" else None)
        if ddc.available:
            logger.info("Backlight: ddcutil")
            return ddc
        if backend == "ddcutil":
            logger.error("Backlight backend 'ddcutil' configured but binary not found")
            return NullBacklight()

    if backend not in ("auto", "none"):
        logger.warning("Unknown backlight backend %r; using none", backend)
    logger.info("Backlight: none (browser overlay fallback)")
    return NullBacklight()
