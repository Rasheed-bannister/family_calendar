import datetime
import calendar
import threading
from flask import Blueprint, render_template, redirect, url_for, jsonify, current_app

from .models import CalendarMonth
from . import (
    database as db,
    utils as calendar_utils
)

from src.google_integration import (
    api as calendar_api,
    tasks_api
)

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

        is_relevant = False
        if start_date <= target_date < end_date:
            is_relevant = True
        elif start_date == target_date and start_date == end_date:
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

    task_id = f"{current_month}.{current_year}"
    start_background_task = False
    with google_fetch_lock:
        task_info = background_tasks.get(task_id)
        if not task_info or task_info['status'] not in ['running', 'complete']:
            start_background_task = True

    if start_background_task:
        from src.google_integration.routes import fetch_google_events_background
        google_thread = threading.Thread(
            target=fetch_google_events_background,
            args=(current_month, current_year)
        )
        google_thread.daemon = True
        google_thread.start()

    db_events = db.get_all_events(current_calendar_month)

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

    with google_fetch_lock:
        chores_to_display = list(last_known_chores)

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
    
    task_id = f"{month}.{year}"
    slideshow_db.sync_photos(current_app.static_folder)  # Using current_app instead of app

    updates_available = False
    task_status = "not_tracked"
    events_changed = False
    chores_changed = False

    with google_fetch_lock:
        task_info = background_tasks.get(task_id)
        if task_info:
            task_status = task_info['status']
            if task_status == 'complete':
                # Read the update status
                updates_available = task_info.get('updated', False)
                events_changed = task_info.get('events_changed', False)
                chores_changed = task_info.get('chores_changed', False)

                # Reset the flags after reading to prevent re-triggering
                if updates_available:
                    task_info['updated'] = False
                    task_info['events_changed'] = False
                    task_info['chores_changed'] = False

    return jsonify({
        "status": task_status,
        "updates_available": updates_available,
        "events_changed": events_changed,
        "chores_changed": chores_changed
    })