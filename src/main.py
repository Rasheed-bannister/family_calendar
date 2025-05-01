import datetime
import calendar
import threading
import os
from flask import Flask, render_template, redirect, url_for, jsonify, request

from google_integration import api as google_api
from google_integration import tasks_api  # <-- Import tasks_api
from calendar_app import database as db
from calendar_app import utils as calendar_utils
from calendar_app.models import CalendarMonth
from slideshow import database as slideshow_db
from weather_integration.api import get_weather_data  # <-- Import weather function
from weather_integration.utils import get_weather_icon # <-- Import the helper

app = Flask(__name__)
app.jinja_env.globals.update(get_weather_icon=get_weather_icon) # <-- Register helper

# Initialize the database if it doesn't exist
calendar_utils.initialize_db()

# Initialize and sync the slideshow database
slideshow_db.init_db()
slideshow_db.sync_photos(app.static_folder)

# Global lock for Google API fetching
google_fetch_lock = threading.Lock()
# Dict to track background task status by month/year
background_tasks = {}
# Global variable to store the last known chores list
last_known_chores = []


def fetch_google_events_background(month, year):
    """Fetches Google Calendar events and Tasks in a background thread and updates the local DB/cache."""
    global last_known_chores  # Allow modification of the global variable
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
        # --- Fetch Calendar Events ---
        current_calendar_month = CalendarMonth(year=year, month=month)
        db.add_month(current_calendar_month)
        processed_google_events_data = google_api.fetch_and_process_google_events(month, year)

        events_to_add_or_update = []
        calendars_changed = False
        events_changed = False  # Initialize events_changed flag

        if processed_google_events_data:
            events_to_add_or_update, calendars_changed = calendar_utils.create_calendar_events_from_google_data(
                processed_google_events_data, current_calendar_month
            )
            if events_to_add_or_update:
                print(f"Processing {len(events_to_add_or_update)} events in database for {month}/{year}...")
                db_changes = calendar_utils.add_events(events_to_add_or_update)
                events_changed = calendars_changed or db_changes  # Combine calendar info and DB changes
            else:
                events_changed = calendars_changed  # Only calendar info might have changed
        else:
            print(f"No events fetched or processed for {month}/{year}.")
            events_changed = False  

        # --- Fetch Google Tasks (Chores) ---
        print(f"Fetching Google Tasks (Chores) for background task {task_id}...")
        current_chores = tasks_api.get_chores()
        chores_changed = False
        with google_fetch_lock:  # Protect access to last_known_chores
            # Convert to sets for order-independent comparison
            # Assumes chores are hashable (e.g., strings, tuples, or objects implementing __hash__ and __eq__)
            # If chores are dicts, a more complex conversion might be needed (e.g., set(tuple(sorted(d.items())) for d in chores))
            try:
                last_known_set = set(last_known_chores)
                current_set = set(current_chores)
            except TypeError:
                 # Fallback for unhashable types (e.g., lists or dicts) - sort and compare strings
                 print("Warning: Chores list contains unhashable items. Comparing sorted string representations.")
                 last_known_set = str(sorted(str(item) for item in last_known_chores))
                 current_set = str(sorted(str(item) for item in current_chores))


            if current_set != last_known_set:
                print(f"Chores list changed. Old: {len(last_known_chores)} items, New: {len(current_chores)} items.")
                last_known_chores = current_chores  # Update the global list
                chores_changed = True
            else:
                print("Chores list unchanged.")

        # --- Determine Overall Update Status ---
        overall_updated = events_changed or chores_changed

        with google_fetch_lock:
            background_tasks[task_id]['updated'] = overall_updated
            if overall_updated:
                print(f"Data changes detected (Events: {events_changed}, Chores: {chores_changed}) for {month}/{year}, notifying client")
            else:
                print(f"No data changes detected for {month}/{year}")

    except Exception as e:
        print(f"An unexpected error occurred in background task {task_id}: {e}")
        with google_fetch_lock:
            background_tasks[task_id]['status'] = 'error'
            background_tasks[task_id]['updated'] = False  # Ensure no refresh on error

    finally:
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
                
                # --- Filter events for *this specific day* ---
                day_events = []
                for event in db_events:
                    start_dt = event['start_datetime']
                    end_dt = event['end_datetime']
                    
                    # Ensure timezone awareness for comparison (assuming UTC if naive)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

                    start_date = start_dt.date()
                    end_date = end_dt.date()

                    # Google API end date for all-day events is exclusive.
                    # Example: An all-day event on May 1st has end date May 2nd.
                    # So, we check if day_date is >= start_date AND < end_date.
                    if start_date <= day_date < end_date:
                         day_events.append(event)
                    # Handle single all-day events where start and end date might be the same in the raw data
                    # or where the event technically ends at 00:00 on the next day.
                    elif event['all_day'] and start_date == day_date and start_date == end_date:
                         day_events.append(event)
                    # Handle non-all-day events that might start and end on the same day
                    elif not event['all_day'] and start_date == day_date and start_date == end_date:
                         day_events.append(event)


                # Sort events for the day: All-day first, then by start time
                day_events.sort(key=lambda x: (not x['all_day'], x['start_datetime']))

                week_data.append({
                    'day_number': day_num,
                    'is_current_month': True,
                    'events': day_events, # Use the filtered and sorted list
                    'is_today': is_today
                })
        weeks_data.append(week_data)

    # --- Filter Events for Today's List (Right Panel) --- #
    today_events = []
    for event in db_events:
        start_dt = event['start_datetime']
        end_dt = event['end_datetime']
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)
            
        start_date = start_dt.date()
        end_date = end_dt.date()

        # Check if today falls within the event's range
        if start_date <= today_date < end_date:
             today_events.append(event)
        elif event['all_day'] and start_date == today_date and start_date == end_date:
             today_events.append(event)
        elif not event['all_day'] and start_date == today_date and start_date == end_date:
             today_events.append(event)

    # Sort today's events as well
    today_events.sort(key=lambda x: (not x['all_day'], x['start_datetime']))

    # --- Fetch Weather Data --- #
    weather_data = None
    try:
        # Check if this is a weather update request from the JavaScript
        is_weather_update = 'Weather-Update-Request' in request.headers
        
        # If it's a weather update request, bypass any caching
        if is_weather_update:
            import importlib
            from weather_integration import api as weather_api
            # Reload the module to ensure fresh data
            importlib.reload(weather_api)
            print("Weather update requested. Fetching fresh weather data...")
        
        weather_data = get_weather_data()
        
        # If it's just a weather update, we could return a minimal response
        # with only the weather data, but for simplicity we'll return the full page
        if is_weather_update:
            print("Returning fresh weather data")
    except Exception as e:
        print(f"Error fetching weather data: {e}")

    # --- Get Chores (from the last known state) --- #
    with google_fetch_lock:  # Access the global variable safely
        chores_to_display = list(last_known_chores) 

    # Get month name for the *displayed* month
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
            # Construct the URL relative to the static folder
            photo_url = url_for('static', filename=f'{slideshow_db.PHOTOS_STATIC_REL_PATH}/{filename}')
            return jsonify({"url": photo_url})
        except Exception as e:
            print(f"Error generating URL for {filename}: {e}")
            return jsonify({"error": "Could not generate photo URL"}), 500
    else:
        # Return a 404 or a default image URL if no photos are found
        return jsonify({"error": "No photos found in database"}), 404


@app.route('/check-updates/<int:year>/<int:month>')
def check_updates(year, month):
    """API endpoint to check if calendar event or task updates are available."""
    task_id = f"{month}.{year}"
    slideshow_db.sync_photos(app.static_folder) # Keep slideshow sync

    event_updates_available = False
    chore_updates_available = False
    task_status = "not_tracked"
    global last_known_chores # Ensure we can modify the global

    # 1. Check background task status for EVENT updates
    with google_fetch_lock:
        task_info = background_tasks.get(task_id)
        if task_info:
            task_status = task_info['status']
            event_updated_flag = task_info.get('updated', False)

            if task_status == 'complete' and event_updated_flag:
                # Reset the flag only if we are confirming an update based on it
                task_info['updated'] = False 
                event_updates_available = True
                print(f"Background task for {month}/{year} reported event updates.")
            elif task_status == 'complete':
                 print(f"Checked event updates for {month}/{year}: Task complete, no *new* event changes reported by background task.")
            elif task_status == 'running':
                print(f"Checked event updates for {month}/{year}: Background task still running.")
            elif task_status == 'error':
                 print(f"Checked event updates for {month}/{year}: Background task encountered an error.")

    # 2. Actively check for CHORE updates NOW
    try:
        print(f"Actively fetching chores for update check ({month}/{year})...")
        current_chores = tasks_api.get_chores()
        
        with google_fetch_lock: # Protect access to last_known_chores
             # Use the same set comparison logic as the background task
            try:
                last_known_set = set(last_known_chores)
                current_set = set(current_chores)
            except TypeError:
                 # Fallback for unhashable types
                 print("Warning (check-updates): Chores list contains unhashable items. Comparing sorted string representations.")
                 last_known_set = str(sorted(str(item) for item in last_known_chores))
                 current_set = str(sorted(str(item) for item in current_chores))

            if current_set != last_known_set:
                print(f"Chore changes detected by check-updates. Old: {len(last_known_chores)}, New: {len(current_chores)}")
                last_known_chores = current_chores # Update the global list
                chore_updates_available = True
            else:
                 print("No chore changes detected by check-updates.")

    except Exception as e:
        print(f"Error fetching chores during update check: {e}")
        # Decide if you want to trigger an update on error or just log it
        # chore_updates_available = False # Keep it false on error for now

    # 3. Combine results and respond
    updates_available = event_updates_available or chore_updates_available
    
    print(f"Update check result for {month}/{year}: Events={event_updates_available}, Chores={chore_updates_available}, Overall={updates_available}")

    return jsonify({
        "status": task_status, # Still useful to know background task state
        "updates_available": updates_available
    })


@app.route('/api/weather-update')
def weather_update():
    """API endpoint to get fresh weather data."""
    try:
        # Force bypassing of cache by manually clearing it first
        import os
        if os.path.exists('.cache'):
            os.remove('.cache')
            print("Removed weather cache file")
        
        # Get fresh weather data
        weather_data = get_weather_data()
        
        if weather_data and weather_data.get('current') and weather_data.get('daily'):
            # Return just the weather portion as a fragment
            return render_template('weather_fragment.html', weather=weather_data)
        else:
            return jsonify({"error": "Could not fetch weather data"}), 500
    except Exception as e:
        print(f"Error updating weather data: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    print("Performing initial chore fetch on startup...")
    last_known_chores = tasks_api.get_chores()
    print(f"Initial chores fetched: {len(last_known_chores)} items")
    app.run(host='0.0.0.0', port=5000, debug=True)
