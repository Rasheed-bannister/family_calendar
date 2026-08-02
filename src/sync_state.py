"""Shared state for background sync tasks.

This module owns the background-task registry, the lock that guards it, and
the worker pool that runs syncs. It deliberately has no imports from the rest
of the application, so blueprints can import it directly instead of importing
from ``src.main`` -- which used to create an import cycle (``src.main`` imports
the blueprints, the blueprints imported ``src.main``) that was worked around
with deferred function-level imports scattered through the routes.

Why a registry rather than a bare dict
--------------------------------------
The task state used to live in a plain module-level dict that four modules
read and wrote directly. Nothing owned the status lifecycle, and every caller
re-implemented "is it safe to start this?" slightly differently. That produced
two real outages:

* A route set a task's status to ``running`` and then invoked the worker,
  whose first act is to bail out if the status is already ``running``. The
  sync silently never ran and the status stayed ``running`` forever, which
  also blocked every future sync of that task.
* Workers indexed ``tasks[task_id]`` unconditionally inside their own
  ``except``/``finally`` blocks, so an entry cleared mid-flight killed the
  worker thread from inside its error handler.

The fix in both cases was a discipline ("callers may only reserve, the worker
owns the lifecycle") that nothing enforced. Here it is enforced by
construction: :meth:`SyncRegistry.submit` is the only way to start a sync, and
it performs the claim itself, so a caller has no opportunity to write a status.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Task lifecycle. A task moves PENDING -> RUNNING -> COMPLETE|ERROR.
# Only the worker performs the transitions after PENDING.
PENDING = "pending"
RUNNING = "running"
COMPLETE = "complete"
ERROR = "error"

# Statuses meaning a sync is already queued or executing, so a second one
# would be redundant work against the same Google API quota.
IN_FLIGHT = (PENDING, RUNNING)

DEFAULT_MAX_WORKERS = 3


class SyncRegistry:
    """Thread-safe registry of background sync tasks and their worker pool."""

    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS):
        # Exposed so ``src.main`` can alias it for backwards compatibility.
        # Prefer the methods below: they take the lock and tolerate an entry
        # that has been cleared out from under a running worker.
        self.tasks: dict[str, dict] = {}
        # Reentrant: submit() claims while already holding the lock.
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="sync"
        )

    # -- reads ---------------------------------------------------------

    def snapshot(self, task_id: str) -> Optional[dict]:
        """Return a copy of a task's state, or None if it is not tracked.

        A copy, so callers can read fields without racing a worker that is
        mutating the live entry.
        """
        with self.lock:
            entry = self.tasks.get(task_id)
            return dict(entry) if entry is not None else None

    def status(self, task_id: str) -> Optional[str]:
        """Current status string, or None if the task is not tracked."""
        with self.lock:
            entry = self.tasks.get(task_id)
            return entry.get("status") if entry else None

    def is_in_flight(self, task_id: str) -> bool:
        """True if a sync for this task is already queued or executing."""
        return self.status(task_id) in IN_FLIGHT

    def is_stale(self, task_id: str, max_age_seconds: float) -> bool:
        """True if the task finished longer than ``max_age_seconds`` ago.

        Untracked tasks count as stale: they have never run. A task that is
        currently in flight is never stale -- a refresh is already coming.
        """
        with self.lock:
            entry = self.tasks.get(task_id)
            if entry is None:
                return True
            if entry.get("status") in IN_FLIGHT:
                return False
            last = entry.get("last_update_time", 0)
            return (time.time() - last) > max_age_seconds

    # -- writes (worker-owned) -----------------------------------------

    def claim(self, task_id: str, **initial: Any) -> bool:
        """Reserve a task at PENDING. False if one is already in flight.

        Callers should not need this directly -- :meth:`submit` calls it.
        """
        with self.lock:
            if self.is_in_flight(task_id):
                return False
            state: dict = {"updated": False}
            state.update(initial)
            state["status"] = PENDING
            self.tasks[task_id] = state
            return True

    def mark_running(self, task_id: str, **initial: Any) -> bool:
        """Worker entry point: transition to RUNNING.

        False if another worker is already running this task, in which case
        the caller should return without doing the work.
        """
        with self.lock:
            if self.status(task_id) == RUNNING:
                return False
            state: dict = {"updated": False}
            state.update(initial)
            state["status"] = RUNNING
            self.tasks[task_id] = state
            return True

    def update(self, task_id: str, **fields: Any) -> None:
        """Merge fields into a task entry, recreating it if it has vanished.

        Never raises. Workers call this from ``except``/``finally`` blocks,
        where a KeyError would replace the original failure with a dead
        thread, so a missing entry must be tolerated rather than assumed.
        """
        with self.lock:
            self.tasks.setdefault(task_id, {}).update(fields)

    def finalize(self, task_id: str) -> None:
        """Mark a task COMPLETE unless the worker already recorded an ERROR."""
        with self.lock:
            entry = self.tasks.setdefault(task_id, {})
            if entry.get("status") != ERROR:
                entry["status"] = COMPLETE
            entry["last_update_time"] = time.time()

    def consume_flag(self, task_id: str, flag: str) -> bool:
        """Read a boolean flag and clear it, atomically.

        Used by the polling endpoint to report "something changed" exactly
        once. Reading and clearing under one lock acquisition means a worker
        that sets the flag between the read and the write cannot have its
        update silently dropped.
        """
        with self.lock:
            entry = self.tasks.get(task_id)
            if not entry or not entry.get(flag):
                return False
            entry[flag] = False
            entry["updated"] = False
            return True

    def clear(self) -> None:
        """Drop all task state. Used at startup to shed stale entries."""
        with self.lock:
            self.tasks.clear()
        logger.info("Cleared background task registry")

    # -- the only way to start work ------------------------------------

    def submit(
        self, task_id: str, fn: Callable[..., Any], *args: Any, **initial: Any
    ) -> bool:
        """Claim ``task_id`` and queue ``fn`` on the worker pool.

        Returns True if the sync was queued, False if one was already in
        flight. This is the single entry point for starting a sync: it owns
        the claim, so no caller is in a position to write a status itself.

        If the pool rejects the work the task is marked ERROR rather than
        being left latched at PENDING, which would block all future syncs.
        """
        if not self.claim(task_id, **initial):
            return False
        try:
            self.executor.submit(fn, *args)
        except Exception:
            self.update(task_id, status=ERROR, updated=False)
            raise
        return True


# Application-wide singleton.
registry = SyncRegistry()
