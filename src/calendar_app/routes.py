import datetime
import calendar
import threading
from flask import Blueprint, render_template, jsonify, current_app

from .models import CalendarMonth
from . import (
    database as db,
    utils as calendar_utils
)

# Now only importing the calendar API
from src.google_integration import api as calendar_api

# Shared resources
from src.main import google_fetch_lock, background_tasks, last_known_chores

calendar_bp = Blueprint('calendar', __name__, url_prefix='/calendar')

def _filter_events_for_day(events, target_date):
    """Filters and sorts a list of events for a specific target date."""
    day_events = []
    for event in events:
        start_dt = event['start_datetime']
        end_dt = event['end_datetime']

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

        start_date = start_dt.date()
        end_date = end_dt.date()

        # Handle events ending exactly at midnight (00:00) of the end day
        is_midnight_end = end_dt.hour == 0 and end_dt.minute == 0 and end_dt.second == 0
        
        # If event ends exactly at midnight, include it on the previous day
        adjusted_end_date = end_date
        if is_midnight_end:
            adjusted_end_date = end_date

        is_relevant = False
        
        # Case 1: For single-day events (start and end on same day)
        if start_date == end_date:
            is_relevant = (target_date == start_date)
            
        # Case 2: For multi-day events
        else:
            # Check if the target date falls within the event's range
            # The end date is inclusive now
            if start_date <= target_date <= end_date:
                # Special case for midnight endings
                if target_date == end_date and is_midnight_end and start_date != end_date:
                    # Don't show events that end at 00:00 on their end date
                    # (unless it's a same-day event)
                    is_relevant = False
                else:
                    is_relevant = True

        if is_relevant:
            day_events.append(event)

    day_events.sort(key=lambda x: (not x['all_day'], x['start_datetime']))
    return day_events


@calendar_bp.route('/')
@calendar_bp.route('/<int:year>/<int:month>')
def view(year=None, month=None):
    """Renders the calendar view for a specific month and year."""
    from src.weather_integration.api import get_weather_data
    
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if not 1 <= month <= 12:
        return "Invalid month", 404

    current_year = year
    current_month = month
    today_date = now.date()
    first_day_of_current_month = datetime.date(current_year, current_month, 1)

    prev_month_date = first_day_of_current_month - datetime.timedelta(days=1)
    prev_month = prev_month_date.month
    prev_year = prev_month_date.year

    if current_month == 12:
        next_month = 1
        next_year = current_year + 1
    else:
        next_month = current_month + 1
        next_year = current_year

    current_calendar_month = CalendarMonth(year=current_year, month=current_month)
    db.add_month(current_calendar_month)

    # Only fetch calendar events, not tasks
    task_id = f"calendar.{current_month}.{current_year}"
    start_background_task = False
    with google_fetch_lock:
        task_info = background_tasks.get(task_id)
        if not task_info or task_info['status'] not in ['running', 'complete']:
            start_background_task = True
        elif task_info['status'] == 'complete':
            # Check if it's been more than 5 minutes since last update
            import time
            last_update_time = task_info.get('last_update_time', 0)
            current_time = time.time()
            if current_time - last_update_time > 300:  # 5 minutes = 300 seconds
                start_background_task = True
                task_info['status'] = 'pending_refresh'  # Mark for refresh

    if start_background_task:
        from src.google_integration.routes import fetch_google_events_background
        google_thread = threading.Thread(
            target=fetch_google_events_background,
            args=(current_month, current_year)
        )
        google_thread.daemon = True
        google_thread.start()

    # Start a separate background task for chores/tasks if not already running
    chores_task_id = "tasks"
    start_chores_background_task = False
    with google_fetch_lock:
        chores_task_info = background_tasks.get(chores_task_id)
        if not chores_task_info or chores_task_info['status'] not in ['running', 'complete']:
            start_chores_background_task = True

    if start_chores_background_task:
        from src.google_integration.routes import fetch_google_tasks_background
        chores_thread = threading.Thread(
            target=fetch_google_tasks_background
        )
        chores_thread.daemon = True
        chores_thread.start()

    # Use the new function to get all events that overlap with this month
    # This ensures we get multi-day events that span across month boundaries
    db_events = db.get_all_events_for_month_range(current_year, current_month)

    calendar.setfirstweekday(calendar.SUNDAY)
    month_calendar = calendar.monthcalendar(current_year, current_month)
    weeks_data = []
    for week in month_calendar:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append({
                    'day_number': '',
                    'is_current_month': False,
                    'events': [],
                    'is_today': False
                })
            else:
                day_date = datetime.date(current_year, current_month, day_num)
                is_today = (day_date == today_date)
                day_events = _filter_events_for_day(db_events, day_date)

                week_data.append({
                    'day_number': day_num,
                    'is_current_month': True,
                    'events': day_events,
                    'is_today': is_today
                })
        weeks_data.append(week_data)

    today_events = _filter_events_for_day(db_events, today_date)

    weather_data = None
    try:
        weather_data = get_weather_data()
    except Exception as e:
        pass

    # Get chores from database instead of direct API call
    from src.chores_app import database as chores_db
    chores_to_display = chores_db.get_chores()

    month_name = calendar.month_name[current_month]

    return render_template(
        'index.html',
        weeks=weeks_data,
        today_events=today_events,
        chores=chores_to_display, 
        weather=weather_data, 
        month_name=month_name,
        month_number=current_month,
        year=current_year,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        today_actual_day=today_date.day,
        today_actual_month=today_date.month,
        today_actual_year=today_date.year,
    )


@calendar_bp.route('/check-updates/<int:year>/<int:month>')
def check_updates(year, month):
    """API endpoint to check if the background task detected calendar or chore updates."""
    from src.slideshow import database as slideshow_db
    import threading
    import time
    
    calendar_task_id = f"calendar.{month}.{year}"
    chores_task_id = "tasks"
    slideshow_db.sync_photos(current_app.static_folder)

    updates_available = False
    calendar_task_status = "not_tracked"
    chores_task_status = "not_tracked"
    events_changed = False
    chores_changed = False
    should_trigger_refresh = False

    with google_fetch_lock:
        # Check calendar task
        calendar_task_info = background_tasks.get(calendar_task_id)
        if calendar_task_info:
            calendar_task_status = calendar_task_info['status']
            if calendar_task_status == 'complete':
                events_changed = calendar_task_info.get('events_changed', False)
                if events_changed:
                    updates_available = True
                    calendar_task_info['events_changed'] = False
                    calendar_task_info['updated'] = False
                    
                # Check if we need to trigger a refresh due to time elapsed
                last_update_time = calendar_task_info.get('last_update_time', 0)
                current_time = time.time()
                if current_time - last_update_time > 300:  # 5 minutes = 300 seconds
                    should_trigger_refresh = True
                    calendar_task_info['status'] = 'pending_refresh'
        else:
            # No task exists, we should create one
            should_trigger_refresh = True
        
        # Check chores task
        chores_task_info = background_tasks.get(chores_task_id)
        if chores_task_info:
            chores_task_status = chores_task_info['status']
            if chores_task_status == 'complete':
                chores_changed = chores_task_info.get('chores_changed', False)
                if chores_changed:
                    updates_available = True
                    chores_task_info['chores_changed'] = False
                    chores_task_info['updated'] = False

    # Trigger background refresh if needed
    if should_trigger_refresh:
        from src.google_integration.routes import fetch_google_events_background
        google_thread = threading.Thread(
            target=fetch_google_events_background,
            args=(month, year)
        )
        google_thread.daemon = True
        google_thread.start()
        print(f"Triggered background refresh for {month}/{year} due to time elapsed or missing task")

    return jsonify({
        "calendar_status": calendar_task_status,
        "chores_status": chores_task_status,
        "updates_available": updates_available,
        "events_changed": events_changed,
        "chores_changed": chores_changed,
        "refresh_triggered": should_trigger_refresh
    })