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
from src.main import google_fetch_lock, background_tasks, last_known_chores, _make_chores_comparable

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


def update_google_task(chore_id, updates):
    """
    Updates a specific task in Google Tasks and then refreshes the local database.
    This function performs both the remote update and triggers a local refresh.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # First update in Google
        success = tasks_api.update_chore(chore_id, updates=updates)
        if not success:
            return False
            
        # Then trigger a refresh of the local database
        # We do this in the foreground since it's an immediate update
        # that the user expects to see
        current_chores_data = tasks_api.get_chores()
        chores_from_google = chores_utils.create_chores_from_google_data(current_chores_data)
        chores_db.add_chores(chores_from_google)
        return True
    
    except Exception as e:
        print(f"Error updating Google task {chore_id}: {e}")
        return False


def mark_task_completed(chore_id):
    """
    Marks a task as completed in Google Tasks and updates the local database.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Call the specialized function in tasks_api
        success = tasks_api.mark_chore_completed(chore_id)
        if not success:
            return False
            
        # Refresh the local database
        current_chores_data = tasks_api.get_chores()
        chores_from_google = chores_utils.create_chores_from_google_data(current_chores_data)
        chores_db.add_chores(chores_from_google)
        return True
    
    except Exception as e:
        print(f"Error marking task {chore_id} as completed: {e}")
        return False


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

@get_google_bp().route('/refresh-tasks')
def refresh_tasks():
    """Manually trigger a refresh of tasks/chores data"""
    from src.main import google_fetch_lock, background_tasks
    import threading
    
    task_id = "tasks"
    
    # Check if already running
    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            return jsonify({'message': 'Tasks refresh already in progress'}), 202
    
    # Start a background thread to fetch tasks
    tasks_thread = threading.Thread(
        target=fetch_google_tasks_background
    )
    tasks_thread.daemon = True
    tasks_thread.start()
    
    return jsonify({
        'message': 'Tasks refresh started',
        'task_id': task_id
    }), 202

@get_google_bp().route('/status')
def status():
    """Get the status of all Google API background tasks"""
    from src.main import google_fetch_lock, background_tasks
    import time
    
    with google_fetch_lock:
        # Create a copy of the tasks for the response with human-readable timestamps
        tasks_status = {}
        current_time = time.time()
        
        for k, v in background_tasks.items():
            task_copy = v.copy()
            
            # Add human-readable timestamps
            if 'last_update_time' in task_copy:
                last_update = task_copy['last_update_time']
                task_copy['last_update_ago_seconds'] = int(current_time - last_update)
                task_copy['last_update_human'] = time.ctime(last_update)
            
            tasks_status[k] = task_copy
    
    return jsonify({
        'tasks': tasks_status,
        'current_time': time.ctime(current_time)
    })