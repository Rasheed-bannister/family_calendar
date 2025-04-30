import datetime
import calendar
import threading
from flask import Flask, render_template, redirect, url_for, jsonify
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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


def parse_google_datetime(google_date_obj):
    """Parses Google API's date or dateTime object into a timezone-aware datetime."""
    dt_str = google_date_obj.get('dateTime', google_date_obj.get('date'))
    is_all_day = 'dateTime' not in google_date_obj

    if is_all_day:
        # For all-day events, Google provides 'YYYY-MM-DD'
        # Represent as start of the day UTC
        dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)
    else:
        # For specific time events, Google provides RFC3339 format
        try:
            # Handle 'Z' for UTC explicitly
            if dt_str.endswith('Z'):
                dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            else:
                dt = datetime.datetime.fromisoformat(dt_str)
            # Ensure timezone-aware (assume UTC if naive, though Google API usually provides offset)
            if dt.tzinfo is None:
                 dt = dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            print(f"Warning: Could not parse datetime string '{dt_str}'. Using epoch.")
            dt = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    return dt, is_all_day


def fetch_google_events_background(month, year):
    """Fetches Google Calendar events in a background thread."""
    task_id = f"{month}.{year}"
    
    # Skip if a task is already running for this month/year
    with google_fetch_lock:
        if task_id in background_tasks and background_tasks[task_id]['status'] == 'running':
            return
        
        # Mark task as running
        background_tasks[task_id] = {'status': 'running', 'updated': False}
    
    try:
        # Create month if it doesn't exist
        current_calendar_month = CalendarMonth(year=year, month=month)
        db.add_month(current_calendar_month)
        
        # Fetch and process Google events
        creds = google_api.authenticate()
        processed_google_events = []
        events_changed = False

        if creds:
            try:
                service = build("calendar", "v3", credentials=creds)
                google_events_raw = google_api.get_events_current_month(service, month, year)

                if google_events_raw:
                    for event_data in google_events_raw:
                        google_cal_id = event_data.get('organizer', {}).get('email', 'primary')
                        google_cal_summary = event_data.get('organizer', {}).get('displayName', google_cal_id)
                        calendar_obj = db.get_calendar(google_cal_id)
                        calendar_changed = False
                        
                        if not calendar_obj:
                            calendar_obj = Calendar(calendar_id=google_cal_id, name=google_cal_summary)
                            db.add_calendar(calendar_obj)
                            calendar_changed = True
                        elif calendar_obj.name != google_cal_summary:
                             calendar_obj.name = google_cal_summary
                             db.add_calendar(calendar_obj)
                             calendar_changed = True
                        
                        if calendar_changed:
                            events_changed = True

                        start_datetime, start_all_day = parse_google_datetime(event_data['start'])
                        end_datetime, end_all_day = parse_google_datetime(event_data['end'])
                        is_all_day = start_all_day

                        event = CalendarEvent(
                            id=event_data['id'],
                            calendar=calendar_obj,
                            month=current_calendar_month,
                            title=event_data.get('summary', '(No Title)'),
                            start_datetime=start_datetime,
                            end_datetime=end_datetime,
                            all_day=is_all_day,
                            location=event_data.get('location'),
                            description=event_data.get('description')
                        )
                        
                        processed_google_events.append(event)
                    
                    if processed_google_events:
                        print(f"Processing {len(processed_google_events)} events from Google Calendar for {month}/{year}...")
                        # Use the return value from add_events to determine if changes were made
                        db_changes = calendar_utils.add_events(processed_google_events)
                        
                        # Only mark as updated if we found new or changed events
                        events_changed = events_changed or db_changes
                        
                        with google_fetch_lock:
                            background_tasks[task_id]['updated'] = events_changed
                            if events_changed:
                                print(f"Calendar changes detected for {month}/{year}, notifying client")
                                background_tasks[task_id]['updated'] = True  # Ensure update flag is set to True for client refresh
                            else:
                                print(f"No changes detected for {month}/{year}")

            except HttpError as error:
                print(f"An API error occurred: {error}")
            except Exception as e:
                print(f"An unexpected error occurred during Google API interaction: {e}")
        else:
            print("Google Calendar authentication failed or skipped.")
    
    finally:
        # Mark task as complete
        with google_fetch_lock:
            background_tasks[task_id]['status'] = 'complete'


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

    # Start a background thread to fetch Google Calendar data
    task_id = f"{current_month}.{current_year}"
    google_thread = threading.Thread(
        target=fetch_google_events_background,
        args=(current_month, current_year)
    )
    google_thread.daemon = True  # Thread will exit when main thread exits
    google_thread.start()
    
    # --- Fetch Events from Local Database for the *Displayed* Month --- #
    # This happens immediately while Google data is being fetched in the background
    db_events = db.get_all_events(current_calendar_month)

    # --- Organize Events by Day --- #
    events_by_day = {}
    for event in db_events:
        event_date = event['start_datetime'].date()
        if event_date.year == current_year and event_date.month == current_month:
            day_num = event_date.day
            if day_num not in events_by_day:
                events_by_day[day_num] = []
            events_by_day[day_num].append(event)

    for day_num in events_by_day:
        events_by_day[day_num].sort(key=lambda x: (x['all_day'], x['start_datetime']))

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
        today_events.sort(key=lambda x: (x['all_day'], x['start_datetime']))

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
        if task_id in background_tasks:
            task = background_tasks[task_id]
            status = task['status']
            updated = task.get('updated', False)
            
            response = {
                "status": status,
                "updates_available": False
            }
            
            # If task is complete and there were updates, tell client to refresh
            if status == 'complete' and updated:
                # Reset the updated flag
                task['updated'] = False
                response["updates_available"] = True
                
            return jsonify(response)
    
    # If no task found for this month/year, create one
    return jsonify({"status": "not_started", "updates_available": False})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
