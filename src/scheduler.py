"""A small periodic job runner for background syncing.

Why this exists
---------------
Syncing used to be driven entirely by the browser: a page render triggered a
calendar and chores sync, and a polling loop in app.js re-triggered them every
few minutes. That has two consequences on a wall-mounted display.

* Nothing syncs unless a browser is pointed at the app. A Pi whose browser
  crashed, or that is showing the screensaver after the tab was closed, holds
  stale data indefinitely.
* The freshness of the data is coupled to the behaviour of a client. A single
  wedged flag in the request path stopped all syncing -- which is exactly the
  outage this branch started with.

The scheduler decouples the two: it keeps the local database current on its
own cadence, and requests become readers of whatever is already there.

Design notes
------------
* No imports from the rest of the application, so it cannot participate in an
  import cycle and can be tested in isolation. Callers register plain
  callables.
* :meth:`run_due_jobs` is public and synchronous -- the background thread is a
  thin loop around it. Tests drive the scheduling logic directly with a fake
  clock instead of sleeping.
* Intervals may be callables, so a config change takes effect on the next tick
  rather than requiring a restart.
* A job that raises is logged and rescheduled. One failing job must never kill
  the thread and silently stop every other job, which is the failure mode that
  makes background workers so unpleasant to debug.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

logger = logging.getLogger(__name__)

# How often the loop wakes to look for due jobs. Jobs have their own intervals;
# this only bounds how late a job can fire, and how fast stop() is noticed.
DEFAULT_TICK_SECONDS = 15.0

IntervalSpec = Union[float, Callable[[], float]]


@dataclass
class _Job:
    name: str
    fn: Callable[[], None]
    interval: IntervalSpec
    next_due: float = 0.0
    run_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = field(default=None)

    def interval_seconds(self) -> float:
        """Resolve the interval, tolerating a bad config value."""
        try:
            value = float(self.interval() if callable(self.interval) else self.interval)
        except Exception:
            logger.warning(
                "Job %s has an unreadable interval; defaulting to 300s", self.name
            )
            return 300.0
        # A non-positive interval would busy-loop the scheduler.
        return value if value > 0 else 300.0


class SyncScheduler:
    """Runs registered callables on their own intervals, on one thread."""

    def __init__(self, thread_name: str = "sync-scheduler"):
        self._jobs: list[_Job] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_name = thread_name

    # -- registration --------------------------------------------------

    def add_job(
        self,
        name: str,
        fn: Callable[[], None],
        interval: IntervalSpec,
        run_immediately: bool = True,
    ) -> None:
        """Register a job.

        ``run_immediately`` fires the job on the first tick rather than after
        one full interval, so a freshly started process populates its data
        without waiting several minutes with an empty screen.
        """
        job = _Job(name=name, fn=fn, interval=interval)
        # next_due 0.0 is always in the past, so the job fires on the first
        # tick. Otherwise push it a full interval out -- scheduling it at
        # "now" would still fire on the next tick, which is not what the
        # caller asked for.
        job.next_due = (
            0.0 if run_immediately else time.monotonic() + job.interval_seconds()
        )
        with self._lock:
            self._jobs.append(job)

    # -- execution -----------------------------------------------------

    def run_due_jobs(self, now: Optional[float] = None) -> list[str]:
        """Run every job whose next_due has passed. Returns the names run.

        Synchronous and safe to call directly -- the thread loop is only a
        wrapper around this. Exceptions are contained per job.
        """
        now = time.monotonic() if now is None else now
        with self._lock:
            jobs = list(self._jobs)

        ran = []
        for job in jobs:
            if now < job.next_due:
                continue
            # Reschedule before running: if fn raises or runs long, the job
            # still moves forward instead of firing again on every tick.
            job.next_due = now + job.interval_seconds()
            try:
                job.fn()
                job.run_count += 1
            except Exception as e:
                job.error_count += 1
                job.last_error = str(e)
                logger.error("Scheduled job %s failed: %s", job.name, e, exc_info=True)
            ran.append(job.name)
        return ran

    # -- lifecycle -----------------------------------------------------

    def start(self, tick_seconds: float = DEFAULT_TICK_SECONDS) -> bool:
        """Start the background thread. False if it is already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                args=(tick_seconds,),
                name=self._thread_name,
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "Sync scheduler started (%d jobs, %.0fs tick)",
            len(self._jobs),
            tick_seconds,
        )
        return True

    def _loop(self, tick_seconds: float) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_due_jobs()
            except Exception as e:
                # run_due_jobs already contains per-job errors; this only
                # catches a failure in the scheduling machinery itself.
                logger.error("Sync scheduler tick failed: %s", e, exc_info=True)
            # wait() rather than sleep() so stop() is acted on promptly.
            self._stop_event.wait(tick_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the thread to stop and wait briefly for it to finish."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        logger.info("Sync scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def job_status(self) -> list[dict]:
        """Snapshot of registered jobs, for the health endpoint."""
        with self._lock:
            return [
                {
                    "name": j.name,
                    "interval_seconds": j.interval_seconds(),
                    "run_count": j.run_count,
                    "error_count": j.error_count,
                    "last_error": j.last_error,
                }
                for j in self._jobs
            ]


# Application-wide singleton.
scheduler = SyncScheduler()
