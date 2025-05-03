import threading
from . import api as calendar_api, tasks_api
from src.calendar_app.models import CalendarMonth
from src.calendar_app import database as db, utils as calendar_utils

# Shared resources
from src.main import google_fetch_lock, background_tasks, last_known_chores, _make_chores_comparable

def fetch_google_events_background(month, year):
    """Fetches Google Calendar events and Tasks in a background thread and updates the local DB/cache."""
    global last_known_chores
    task_id = f"{month}.{year}"
    events_changed_in_task = False
    chores_changed_in_task = False

    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            return
        background_tasks[task_id] = {'status': 'running', 'updated': False}

    try:
        current_calendar_month = CalendarMonth(year=year, month=month)
        db.add_month(current_calendar_month)
        processed_google_events_data = calendar_api.fetch_and_process_google_events(month, year)

        events_to_add_or_update = []
        calendars_changed = False
        events_changed = False
        events_changed_in_task = events_changed 

        if processed_google_events_data:
            events_to_add_or_update, calendars_changed = calendar_utils.create_calendar_events_from_google_data(
                processed_google_events_data, current_calendar_month
            )
            if events_to_add_or_update:
                db_changes = calendar_utils.add_events(events_to_add_or_update)
                events_changed_in_task = calendars_changed or db_changes
            else:
                events_changed_in_task = calendars_changed
        else:
            events_changed_in_task = False  

        current_chores = tasks_api.get_chores()
        with google_fetch_lock:
            last_known_set = _make_chores_comparable(last_known_chores)
            current_set = _make_chores_comparable(current_chores)

            if current_set is not None and current_set != last_known_set:
                last_known_chores = current_chores
                chores_changed_in_task = True

        overall_updated = events_changed_in_task or chores_changed_in_task

        with google_fetch_lock:
            background_tasks[task_id]['updated'] = overall_updated
            background_tasks[task_id]['events_changed'] = events_changed_in_task
            background_tasks[task_id]['chores_changed'] = chores_changed_in_task

    except Exception as e:
        with google_fetch_lock:
            background_tasks[task_id]['status'] = 'error'
            background_tasks[task_id]['updated'] = False
            background_tasks[task_id]['events_changed'] = False
            background_tasks[task_id]['chores_changed'] = False
    finally:
        with google_fetch_lock:
            if background_tasks[task_id]['status'] != 'error':
                background_tasks[task_id]['status'] = 'complete'