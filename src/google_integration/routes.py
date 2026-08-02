import logging

from flask import jsonify

# Shared sync state. Imported from src.sync_state rather than src.main so this
# module does not participate in an import cycle with the app factory.
from src import events, sync_state
from src.calendar_app import database as calendar_db
from src.calendar_app import utils as calendar_utils
from src.calendar_app.models import CalendarMonth
from src.chores_app import database as chores_db
from src.chores_app import utils as chores_utils
from src.chores_app.utils import make_chores_comparable
from src.events import broker
from src.sync_state import registry

from . import api as calendar_api
from . import tasks_api

logger = logging.getLogger(__name__)


# Get the blueprint reference - this will be available after __init__.py runs
def get_google_bp():
    from . import google_bp

    return google_bp


TASKS_TASK_ID = "tasks"


def calendar_task_id(month, year) -> str:
    """Registry key for a month's calendar sync."""
    return f"calendar.{month}.{year}"


def start_calendar_sync(month, year) -> bool:
    """Queue a Google Calendar sync for a month.

    Returns False (without queueing) if a sync for that month is already
    pending or running. The registry performs the claim, so no caller is in a
    position to write a status itself -- see src/sync_state.py for why that
    matters.
    """
    return registry.submit(
        calendar_task_id(month, year), fetch_google_events_background, month, year
    )


def start_tasks_sync() -> bool:
    """Queue a Google Tasks (chores) sync.

    Returns False (without queueing) if a chores sync is already pending or
    running.
    """
    return registry.submit(
        TASKS_TASK_ID, fetch_google_tasks_background, chores_changed=False
    )


def fetch_google_events_background(month, year):
    """Fetches Google Calendar events in a background thread and updates the local DB."""
    task_id = calendar_task_id(month, year)

    if not registry.mark_running(task_id):
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
        registry.update(
            task_id,
            updated=events_changed,
            events_changed=events_changed,
        )

        # Tell connected displays to re-fetch the calendar fragment. Only on
        # an actual change: a notification per sync would make every display
        # re-render every few minutes for nothing.
        if events_changed:
            broker.publish(events.CALENDAR_CHANGED, month=month, year=year)

    except Exception as e:
        logger.error("Error in calendar fetch background task %s: %s", task_id, e)
        registry.update(
            task_id,
            status=sync_state.ERROR,
            updated=False,
            events_changed=False,
        )
    finally:
        # Stamps last_update_time for both the success and error paths, which
        # is what the staleness check keys off.
        registry.finalize(task_id)


def fetch_google_tasks_background():
    """
    Fetches Google Tasks (chores) in a background thread and updates the local DB.
    This is completely independent from calendar events fetch.
    """
    task_id = TASKS_TASK_ID

    # Take ownership of the task entry (no-op if another worker already has it)
    if not registry.mark_running(task_id, chores_changed=False):
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
        registry.update(task_id, updated=chores_changed, chores_changed=chores_changed)

        if chores_changed:
            broker.publish(events.CHORES_CHANGED)

    except Exception as e:
        logger.error(
            "Error in tasks fetch background task %s: %s", task_id, e, exc_info=True
        )
        registry.update(
            task_id, status=sync_state.ERROR, updated=False, chores_changed=False
        )
    finally:
        registry.finalize(task_id)


@get_google_bp().route("/refresh-calendar/<int:year>/<int:month>")
def refresh_calendar(year, month):
    """Manually trigger a refresh of calendar events for a specific month"""
    task_id = calendar_task_id(month, year)

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
