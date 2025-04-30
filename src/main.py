import datetime
import calendar
import threading
from flask import Flask, render_template, redirect, url_for, jsonify

from google_integration import api as google_api
from calendar_app import database as db
from calendar_app import utils as calendar_utils
from calendar_app.models import CalendarEvent, CalendarMonth, Calendar

app = Flask(__name__)

# Initialize the database if it doesn't exist
calendar_utils.initialize_db()

# Global lock for Google API fetching
google_fetch_lock = threading.Lock()
# Dict to track background task status by month/year
background_tasks = {}


def fetch_google_events_background(month, year):
    """Fetches Google Calendar events in a background thread and updates the local DB."""
    task_id = f"{month}.{year}"

    # Skip if a task is already running for this month/year
    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            print(f"Task {task_id} already running. Skipping.")
            return

        # Mark task as running
        background_tasks[task_id] = {'status': 'running', 'updated': False}
        print(f"Starting background task {task_id}...")

    try:
        # Create month if it doesn't exist in the DB
        current_calendar_month = CalendarMonth(year=year, month=month)
        db.add_month(current_calendar_month)

        # Fetch and process Google events using the refactored function
        processed_google_events_data = google_api.fetch_and_process_google_events(month, year)

        if not processed_google_events_data:
            print(f"No events fetched or processed for {month}/{year}.")
            # Mark task as complete even if no events, but not updated
            with google_fetch_lock:
                background_tasks[task_id]['status'] = 'complete'
                background_tasks[task_id]['updated'] = False
            return

        # Use the new utility function to create CalendarEvent objects and handle Calendars
        events_to_add_or_update, calendars_changed = calendar_utils.create_calendar_events_from_google_data(
            processed_google_events_data, current_calendar_month
        )

        # Add/update events in the database
        if events_to_add_or_update:
            print(f"Processing {len(events_to_add_or_update)} events in database for {month}/{year}...")
            db_changes = calendar_utils.add_events(events_to_add_or_update)

            # Mark as updated if calendar info changed OR events were added/updated in DB
            events_changed = calendars_changed or db_changes

            with google_fetch_lock:
                background_tasks[task_id]['updated'] = events_changed
                if events_changed:
                    print(f"Calendar changes detected for {month}/{year}, notifying client")
                else:
                    print(f"No database changes detected for {month}/{year}")
        else:
             # If only calendar info changed but no events processed for DB
             with google_fetch_lock:
                 background_tasks[task_id]['updated'] = calendars_changed
                 if calendars_changed:
                     print(f"Calendar info changes detected for {month}/{year}, notifying client")

    except Exception as e:
        print(f"An unexpected error occurred in background task {task_id}: {e}")
        # Optionally mark as error state
        with google_fetch_lock:
            background_tasks[task_id]['status'] = 'error'
            background_tasks[task_id]['updated'] = False # Ensure no refresh on error

    finally:
        # Mark task as complete (unless already marked as error)
        with google_fetch_lock:
            if background_tasks[task_id]['status'] != 'error':
                 background_tasks[task_id]['status'] = 'complete'
        print(f"Background task {task_id} finished with status: {background_tasks[task_id]['status']}")


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

    # Default to current month/year if not provided
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

    # Next month logic (handle year change)
    if current_month == 12:
        next_month = 1
        next_year = current_year + 1
    else:
        next_month = current_month + 1
        next_year = current_year

    # Ensure the displayed month exists in the database
    current_calendar_month = CalendarMonth(year=current_year, month=current_month)
    db.add_month(current_calendar_month)

    # Start a background thread to fetch Google Calendar data if not already running
    task_id = f"{current_month}.{current_year}"
    start_background_task = False
    with google_fetch_lock:
        if task_id not in background_tasks or background_tasks[task_id]['status'] not in ['running', 'complete']:
             start_background_task = True
        elif background_tasks[task_id]['status'] == 'complete' and not background_tasks[task_id].get('updated', False):
            pass

    if start_background_task:
        google_thread = threading.Thread(
            target=fetch_google_events_background,
            args=(current_month, current_year)
        )
        google_thread.daemon = True  # Thread will exit when main thread exits
        google_thread.start()

    # --- Fetch Events from Local Database for the *Displayed* Month --- #
    db_events = db.get_all_events(current_calendar_month)

    # --- Organize Events by Day --- #
    events_by_day = {}
    for event in db_events:
        start_dt = event['start_datetime']
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)

        event_date = start_dt.date()

        if event_date.year == current_year and event_date.month == current_month:
            day_num = event_date.day
            if day_num not in events_by_day:
                events_by_day[day_num] = []
            events_by_day[day_num].append(event)

    for day_num in events_by_day:
        events_by_day[day_num].sort(key=lambda x: (not x['all_day'], x['start_datetime']))

    # --- Generate Calendar Weeks Structure --- #
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
                week_data.append({
                    'day_number': day_num,
                    'is_current_month': True,
                    'events': events_by_day.get(day_num, []),
                    'is_today': is_today
                })
        weeks_data.append(week_data)

    # --- Filter Events for Today's List (Right Panel) --- #
    today_events = []
    if today_date.year == current_year and today_date.month == current_month:
        today_events = events_by_day.get(today_date.day, [])

    # Get month name for the *displayed* month
    month_name = calendar.month_name[current_month]

    return render_template(
        'index.html',
        weeks=weeks_data,
        today_events=today_events,
        month_name=month_name,
        month_number=current_month,
        year=current_year,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        today_actual_day=today_date.day,
        today_actual_month=today_date.month,
        today_actual_year=today_date.year
    )


@app.route('/check-updates/<int:year>/<int:month>')
def check_updates(year, month):
    """API endpoint to check if calendar updates are available."""
    task_id = f"{month}.{year}"

    with google_fetch_lock:
        task_info = background_tasks.get(task_id)

        if task_info:
            status = task_info['status']
            updated = task_info.get('updated', False)

            response = {
                "status": status,
                "updates_available": False
            }

            # If task is complete and there were updates, tell client to refresh
            if status == 'complete' and updated:
                task_info['updated'] = False
                response["updates_available"] = True

            return jsonify(response)

    return jsonify({"status": "not_tracked", "updates_available": False})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
