import threading
from flask import Blueprint, jsonify, request
import datetime
from . import api as calendar_api, tasks_api
from src.calendar_app.models import CalendarMonth

# Get the blueprint reference - this will be available after __init__.py runs
def get_google_bp():
    from . import google_bp
    return google_bp
from src.calendar_app import database as calendar_db, utils as calendar_utils
from src.chores_app import database as chores_db, utils as chores_utils

# Shared resources
from src.main import google_fetch_lock, background_tasks, _make_chores_comparable

def fetch_google_events_background(month, year):
    """Fetches Google Calendar events in a background thread and updates the local DB."""
    task_id = f"calendar.{month}.{year}"

    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            return
        background_tasks[task_id] = {'status': 'running', 'updated': False}

    try:
        # --- Calendar Event Processing ---
        current_calendar_month = CalendarMonth(year=year, month=month)
        calendar_db.add_month(current_calendar_month)
        processed_google_events_data = calendar_api.fetch_and_process_google_events(month, year)

        events_to_add_or_update = []
        calendars_changed = False

        if processed_google_events_data:
            events_to_add_or_update, calendars_changed = calendar_utils.create_calendar_events_from_google_data(
                processed_google_events_data, current_calendar_month
            )
            
            # Clean up events that no longer exist in Google Calendar
            google_event_ids = {event['id'] for event in processed_google_events_data}
            deleted_events = calendar_utils.cleanup_deleted_events(month, year, google_event_ids)
            
            if events_to_add_or_update:
                db_changes = calendar_utils.add_events(events_to_add_or_update)
                events_changed = calendars_changed or db_changes or deleted_events
            else:
                events_changed = calendars_changed or deleted_events
        else:
            events_changed = False

        # --- Update Task Status ---
        with google_fetch_lock:
            import time
            background_tasks[task_id]['updated'] = events_changed
            background_tasks[task_id]['events_changed'] = events_changed
            background_tasks[task_id]['last_update_time'] = time.time()  # Record when this sync completed

    except Exception as e:
        print(f"Error in calendar fetch background task {task_id}: {e}")
        with google_fetch_lock:
            background_tasks[task_id]['status'] = 'error'
            background_tasks[task_id]['updated'] = False
            background_tasks[task_id]['events_changed'] = False
            import time
            background_tasks[task_id]['last_update_time'] = time.time()  # Record error time too
    finally:
        with google_fetch_lock:
            if background_tasks[task_id]['status'] != 'error':
                background_tasks[task_id]['status'] = 'complete'


def fetch_google_tasks_background():
    """
    Fetches Google Tasks (chores) in a background thread and updates the local DB.
    This is completely independent from calendar events fetch.
    """
    task_id = "tasks"
    
    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            return
        background_tasks[task_id] = {'status': 'running', 'updated': False}
    
    try:
        # --- Chore Processing ---
        current_chores_data = tasks_api.get_chores()  # Raw data from Google API
        chores_from_google = chores_utils.create_chores_from_google_data(current_chores_data)

        # Fetch *all* chores from DB, including invisible ones, for comparison logic
        existing_db_chores_all = chores_db.get_chores(include_invisible=True)
        existing_db_chores_dict = {c['id']: c for c in existing_db_chores_all}

        chores_to_add_or_update_in_db = []
        chores_changed = False

        for chore_google in chores_from_google:
            existing_chore = existing_db_chores_dict.get(chore_google.id)
            # If chore exists in DB and is marked 'invisible', skip update from Google
            if existing_chore and existing_chore['status'] == 'invisible':
                continue  # Don't revert 'invisible' status based on Google API
            
            # Otherwise, compare Google data with DB data (if it exists)
            if not existing_chore or _make_chores_comparable([chore_google]) != _make_chores_comparable([existing_chore]):
                chores_to_add_or_update_in_db.append(chore_google)
                chores_changed = True  # Mark as changed if we add/update non-invisible chore

        if chores_to_add_or_update_in_db:
            chores_db.add_chores(chores_to_add_or_update_in_db)  # This function already handles the 'invisible' check on write

        # --- Update Task Status ---
        with google_fetch_lock:
            background_tasks[task_id]['updated'] = chores_changed
            background_tasks[task_id]['chores_changed'] = chores_changed

    except Exception as e:
        print(f"Error in tasks fetch background task {task_id}: {e}")
        with google_fetch_lock:
            background_tasks[task_id]['status'] = 'error'
            background_tasks[task_id]['updated'] = False
            background_tasks[task_id]['chores_changed'] = False
    finally:
        with google_fetch_lock:
            if background_tasks[task_id]['status'] != 'error':
                background_tasks[task_id]['status'] = 'complete'




@get_google_bp().route('/refresh-calendar/<int:year>/<int:month>')
def refresh_calendar(year, month):
    """Manually trigger a refresh of calendar events for a specific month"""
    from src.main import google_fetch_lock, background_tasks
    import threading
    
    task_id = f"calendar.{month}.{year}"
    
    # Check if already running
    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            return jsonify({'message': 'Calendar refresh already in progress'}), 202
            
    # Start a background thread to fetch calendar events
    google_thread = threading.Thread(
        target=fetch_google_events_background,
        args=(month, year)
    )
    google_thread.daemon = True
    google_thread.start()
    
    return jsonify({
        'message': f'Calendar refresh started for {month}/{year}',
        'task_id': task_id
    }), 202
