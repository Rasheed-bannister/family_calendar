"""Process-level runtime: the things that must start exactly once.

``create_app()`` is called many times across the test suite and by tooling,
so it must not open GPIO pins, start ticker threads or reach out to Google.
Everything with that character lives here and is started by the ``__main__``
entrypoint (and by ``wsgi.py`` for a WSGI server), so every way of running
the app gets the same wiring:

* the display service (mode ticker + backlight),
* the PIR sensor, feeding motion into the display service,
* the background sync scheduler (calendar, chores, weather),
* the photo ingest pass (processes new originals into display variants).
"""

from __future__ import annotations

import atexit
import logging
import signal
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    display: Any = None
    pir: Any = None
    scheduler: Any = None
    _threads: list = field(default_factory=list)
    _stopped: bool = False

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        from src.pir_sensor.sensor import remove_motion_callback, shutdown_pir_sensor

        try:
            if self.scheduler is not None:
                self.scheduler.stop()
        except Exception:
            logger.exception("Error stopping scheduler")
        try:
            remove_motion_callback(_motion_to_display)
            shutdown_pir_sensor()
        except Exception:
            logger.exception("Error stopping PIR sensor")
        try:
            if self.display is not None:
                self.display.stop()
        except Exception:
            logger.exception("Error stopping display service")


_runtime: Optional[Runtime] = None
_runtime_lock = threading.Lock()


def _motion_to_display() -> None:
    from src.display.service import get_display_service

    service = get_display_service()
    if service is not None:
        service.activity("pir")


def _ingest_photos(app) -> None:
    """Process any originals that lack a display variant, off the main thread."""
    from src.slideshow import database as slideshow_db

    try:
        slideshow_db.sync_photos(app.static_folder)
    except Exception:
        logger.exception("Photo ingest failed")


def start_runtime(app) -> Runtime:
    """Start every process-level service. Idempotent."""
    global _runtime
    with _runtime_lock:
        if _runtime is not None:
            return _runtime

        from src.config import get_config
        from src.display.service import ensure_display_service
        from src.main import start_background_sync
        from src.pir_sensor.sensor import add_motion_callback, initialize_pir_sensor

        config = get_config()
        runtime = Runtime()

        runtime.display = ensure_display_service(config)
        runtime.display.start()

        add_motion_callback(_motion_to_display)
        runtime.pir = initialize_pir_sensor(config)
        if not runtime.pir.healthy:
            logger.error(
                "PIR sensor is NOT working: %s. Motion wake is unavailable until "
                "this is fixed; see /pir/diagnostics.",
                runtime.pir.error,
            )

        runtime.scheduler = start_background_sync()

        ingest = threading.Thread(
            target=_ingest_photos, args=(app,), name="photo-ingest", daemon=True
        )
        ingest.start()
        runtime._threads.append(ingest)

        _runtime = runtime
        atexit.register(runtime.stop)
        _install_sigterm(runtime)
        return runtime


def _install_sigterm(runtime: Runtime) -> None:
    def handler(_signum, _frame):
        runtime.stop()
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, handler)
    except ValueError:
        # Not on the main thread; atexit still runs on a clean shutdown.
        logger.debug("SIGTERM handler not installed (not main thread)")


def get_runtime() -> Optional[Runtime]:
    return _runtime
