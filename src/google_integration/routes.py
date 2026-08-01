import logging

from flask import jsonify

from src.calendar_app import database as calendar_db
from src.calendar_app import utils as calendar_utils
from src.calendar_app.models import CalendarMonth
from src.chores_app import database as chores_db
from src.chores_app import utils as chores_utils
from src.chores_app.utils import make_chores_comparable

# Shared resources
from src.main import background_tasks, google_fetch_lock

from . import api as calendar_api
from . import tasks_api

logger = logging.getLogger(__name__)


# Get the blueprint reference - this will be available after __init__.py runs
def get_google_bp():
    from . import google_bp

    return google_bp


TASKS_TASK_ID = "tasks"

# Statuses that mean a sync for a task is already queued or executing.
IN_FLIGHT_STATUSES = ("pending", "running")


def _claim_background_task(task_id: str, initial_state: dict | None = None) -> bool:
    """Atomically reserve ``task_id`` for a sync that is about to be queued.

    Returns True when the caller now owns the slot, False when a sync for the
    same task is already pending or running.

    Ownership rule: the background worker owns the *status* lifecycle
    (``pending`` -> ``running`` -> ``complete``/``error``). Callers may only
    reserve a slot through this helper, which parks the task at ``pending``.
    A caller that sets ``running`` itself would trip the worker's own
    "already running" guard and the requested sync would silently never run,
    leaving the status latched at ``running`` forever.
    """
    state: dict = {"updated": False}
    if initial_state:
        state.update(initial_state)
    state["status"] = "pending"

    with google_fetch_lock:
        existing = background_tasks.get(task_id)
        if existing and existing.get("status") in IN_FLIGHT_STATUSES:
            return False
        background_tasks[task_id] = state
        return True


def _mark_task_running(task_id: str, initial_state: dict | None = None) -> bool:
    """Transition a task to ``running``; returns False if it is already running."""
    state: dict = {"updated": False}
    if initial_state:
        state.update(initial_state)
    state["status"] = "running"

    with google_fetch_lock:
        existing = background_tasks.get(task_id)
        if existing and existing.get("status") == "running":
            return False
        background_tasks[task_id] = state
        return True


def _update_background_task(task_id: str, **fields) -> None:
    """Merge ``fields`` into a task entry, recreating it if it has vanished.

    ``background_tasks`` can be cleared out from under a running worker (see
    ``clear_stale_background_tasks`` in src/main.py), so entries must never be
    indexed unconditionally - not even from an ``except``/``finally`` block,
    where a KeyError would kill the worker thread.
    """
    with google_fetch_lock:
        background_tasks.setdefault(task_id, {}).update(fields)


def _finalize_background_task(task_id: str) -> None:
    """Mark a task ``complete`` unless the worker already recorded an error."""
    with google_fetch_lock:
        entry = background_tasks.setdefault(task_id, {})
        if entry.get("status") != "error":
            entry["status"] = "complete"


def start_calendar_sync(month, year) -> bool:
    """Queue a Google Calendar sync for a month on the shared thread pool.

    Returns False (without queueing) if a sync for that month is already
    pending or running.
    """
    from src.main import sync_executor

    task_id = f"calendar.{month}.{year}"
    if not _claim_background_task(task_id):
        return False

    try:
        sync_executor.submit(fetch_google_events_background, month, year)
    except Exception:
        _update_background_task(task_id, status="error", updated=False)
        raise
    return True


def start_tasks_sync() -> bool:
    """Queue a Google Tasks (chores) sync on the shared thread pool.

    Returns False (without queueing) if a chores sync is already pending or
    running. Never sets ``running`` itself - see ``_claim_background_task``.
    """
    from src.main import sync_executor

    if not _claim_background_task(TASKS_TASK_ID, {"chores_changed": False}):
        return False

    try:
        sync_executor.submit(fetch_google_tasks_background)
    except Exception:
        _update_background_task(
            TASKS_TASK_ID, status="error", updated=False, chores_changed=False
        )
        raise
    return True


def fetch_google_events_background(month, year):
    """Fetches Google Calendar events in a background thread and updates the local DB."""
    task_id = f"calendar.{month}.{year}"

    if not _mark_task_running(task_id):
        return

    try:
        # --- Calendar Event Processing ---
        current_calendar_month = CalendarMonth(year=year, month=month)
        calendar_db.add_month(current_calendar_month)
        processed_google_events_data = calendar_api.fetch_and_process_google_events(
            month, year
        )

        events_to_add_or_update = []
        calendars_changed = False

        if processed_google_events_data:
            events_to_add_or_update, calendars_changed = (
                calendar_utils.create_calendar_events_from_google_data(
                    processed_google_events_data, current_calendar_month
                )
            )

            # Clean up events that no longer exist in Google Calendar
            google_event_ids = {event["id"] for event in processed_google_events_data}
            deleted_events = calendar_utils.cleanup_deleted_events(
                month, year, google_event_ids
            )

            if events_to_add_or_update:
                db_changes = calendar_utils.add_events(events_to_add_or_update)
                events_changed = calendars_changed or db_changes or deleted_events
            else:
                events_changed = calendars_changed or deleted_events
        else:
            events_changed = False

        # --- Update Task Status ---
        import time

        _update_background_task(
            task_id,
            updated=events_changed,
            events_changed=events_changed,
            last_update_time=time.time(),  # Record when this sync completed
        )

    except Exception as e:
        logger.error("Error in calendar fetch background task %s: %s", task_id, e)
        import time

        _update_background_task(
            task_id,
            status="error",
            updated=False,
            events_changed=False,
            last_update_time=time.time(),  # Record error time too
        )
    finally:
        _finalize_background_task(task_id)


def fetch_google_tasks_background():
    """
    Fetches Google Tasks (chores) in a background thread and updates the local DB.
    This is completely independent from calendar events fetch.
    """
    task_id = TASKS_TASK_ID

    # Take ownership of the task entry (no-op if another worker already has it)
    if not _mark_task_running(task_id, {"chores_changed": False}):
        return  # Already running

    try:
        # --- Chore Processing ---
        current_chores_data = tasks_api.get_chores()  # Raw data from Google API
        chores_from_google = chores_utils.create_chores_from_google_data(
            current_chores_data
        )

        # Fetch *all* chores from DB, including invisible ones, for comparison logic
        existing_db_chores_all = chores_db.get_chores(include_invisible=True)
        existing_db_chores_dict = {c["id"]: c for c in existing_db_chores_all}

        chores_to_add_or_update_in_db = []
        chores_changed = False

        for chore_google in chores_from_google:
            existing_chore = existing_db_chores_dict.get(chore_google.id)
            # If chore exists in DB and is marked 'invisible', skip update from Google
            if existing_chore and existing_chore["status"] == "invisible":
                continue  # Don't revert 'invisible' status based on Google API

            # Otherwise, compare Google data with DB data (if it exists)
            if not existing_chore or make_chores_comparable(
                [chore_google]
            ) != make_chores_comparable([existing_chore]):
                chores_to_add_or_update_in_db.append(chore_google)
                chores_changed = (
                    True  # Mark as changed if we add/update non-invisible chore
                )

        if chores_to_add_or_update_in_db:
            chores_db.add_chores(
                chores_to_add_or_update_in_db
            )  # This function already handles the 'invisible' check on write

        # --- Update Task Status ---
        _update_background_task(
            task_id, updated=chores_changed, chores_changed=chores_changed
        )

    except Exception as e:
        logger.error(
            "Error in tasks fetch background task %s: %s", task_id, e, exc_info=True
        )
        _update_background_task(
            task_id, status="error", updated=False, chores_changed=False
        )
    finally:
        _finalize_background_task(task_id)


@get_google_bp().route("/refresh-calendar/<int:year>/<int:month>")
def refresh_calendar(year, month):
    """Manually trigger a refresh of calendar events for a specific month"""
    task_id = f"calendar.{month}.{year}"

    # Atomically claim the slot; the worker owns the status from here (#5)
    if not start_calendar_sync(month, year):
        return jsonify({"message": "Calendar refresh already in progress"}), 202

    return (
        jsonify(
            {
                "message": f"Calendar refresh started for {month}/{year}",
                "task_id": task_id,
            }
        ),
        202,
    )
