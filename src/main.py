import datetime
import calendar
import threading
from flask import Flask, render_template, redirect, url_for, jsonify, request

from google_integration import (
    api as calendar_api, 
    tasks_api
)

from calendar_app.models import CalendarMonth
from calendar_app import (
    database as db,
    utils as calendar_utils
)

from slideshow import database as slideshow_db

from weather_integration.api import get_weather_data  
from weather_integration.utils import get_weather_icon

app = Flask(__name__)
app.jinja_env.globals.update(get_weather_icon=get_weather_icon)

# Initialize the database if it doesn't exist
calendar_utils.initialize_db()

# Initialize and sync the slideshow database
slideshow_db.init_db()
slideshow_db.sync_photos(app.static_folder)

google_fetch_lock = threading.Lock()    # Global lock for Google API fetching
background_tasks = {}                   # Dict to track background task status by month/year
last_known_chores = []                  # Global variable to store the last known chores list


def _make_chores_comparable(chores_list):
    """Creates a simplified, comparable representation of the chores list."""
    if not isinstance(chores_list, list):
        return None 
    comparable_set = set()
    for item in chores_list:
        if isinstance(item, dict):
            comparable_set.add((item.get('id'), item.get('title'), item.get('status')))
        else:
            try:
                comparable_set.add(str(item))
            except Exception:
                pass
    return comparable_set


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


@app.route('/')
def index_redirect():
    """Redirects the base URL to the current month's calendar view."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return redirect(url_for('calendar_view', year=now.year, month=now.month))


@app.route('/calendar/')
@app.route('/calendar/<int:year>/<int:month>')
def calendar_view(year=None, month=None):
    """Renders the calendar view for a specific month and year."""
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


@app.route('/api/random-photo')
def random_photo():
    """API endpoint to get a random background photo URL."""
    filename = slideshow_db.get_random_photo_filename()
    if filename:
        try:
            photo_url = url_for('static', filename=f'{slideshow_db.PHOTOS_STATIC_REL_PATH}/{filename}')
            return jsonify({"url": photo_url})
        except Exception as e:
            return jsonify({"error": "Could not generate photo URL"}), 500
    else:
        return jsonify({"error": "No photos found in database"}), 404


@app.route('/check-updates/<int:year>/<int:month>')
def check_updates(year, month):
    """API endpoint to check if the background task detected calendar or chore updates."""
    task_id = f"{month}.{year}"
    slideshow_db.sync_photos(app.static_folder)

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
                    # No need to explicitly update background_tasks[task_id]
                    # as task_info is a reference to the dictionary item

    return jsonify({
        "status": task_status,
        "updates_available": updates_available,
        "events_changed": events_changed,
        "chores_changed": chores_changed
    })


@app.route('/api/weather-update')
def weather_update():
    """API endpoint to get fresh weather data, bypassing any internal cache."""
    try:
        weather_data = get_weather_data()

        if weather_data and weather_data.get('current') and weather_data.get('daily'):
            return render_template('components/weather.html', weather=weather_data)
        else:
            return jsonify({"error": "Could not fetch valid weather data"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    last_known_chores = tasks_api.get_chores()
    # Ignore .db files to prevent reload loop caused by background updates
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=True, exclude_patterns=["**/*.db"])
