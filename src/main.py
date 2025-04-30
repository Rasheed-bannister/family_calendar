import datetime
import calendar
from flask import Flask, render_template, redirect, url_for
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Local imports
from google_integration import api as google_api
from calendar_app import database as db
from calendar_app import utils as calendar_utils
from calendar_app.models import CalendarEvent, CalendarMonth, Calendar

app = Flask(__name__)

# Initialize the database if it doesn't exist
calendar_utils.initialize_db()


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

    # Validate month range
    if not 1 <= month <= 12:
        return "Invalid month", 404

    current_year = year
    current_month = month
    today_date = now.date()  # Keep track of the actual today

    # Calculate previous and next month/year for navigation
    first_day_of_current_month = datetime.date(current_year, current_month, 1)
    
    # Previous month logic
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

    # --- Google Calendar Integration --- #
    creds = google_api.authenticate()
    processed_google_events = []

    if creds:
        try:
            service = build("calendar", "v3", credentials=creds)
            google_events_raw = google_api.get_events_current_month(service, current_month, current_year)

            if google_events_raw:
                print(f"Processing {len(google_events_raw)} events from Google Calendar for {current_month}/{current_year}...")
                for event_data in google_events_raw:
                    google_cal_id = event_data.get('organizer', {}).get('email', 'primary')
                    google_cal_summary = event_data.get('organizer', {}).get('displayName', google_cal_id)
                    calendar_obj = db.get_calendar(google_cal_id)
                    if not calendar_obj:
                        calendar_obj = Calendar(calendar_id=google_cal_id, name=google_cal_summary)
                        db.add_calendar(calendar_obj)
                    elif calendar_obj.name != google_cal_summary:
                         calendar_obj.name = google_cal_summary
                         db.add_calendar(calendar_obj)

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
                    print(f"Adding/updating {len(processed_google_events)} events in the local database for {current_month}/{current_year}...")
                    calendar_utils.add_events(processed_google_events)

        except HttpError as error:
            print(f"An API error occurred: {error}")
        except Exception as e:
            print(f"An unexpected error occurred during Google API interaction: {e}")
    else:
        print("Google Calendar authentication failed or skipped.")

    # --- Fetch Events from Local Database for the *Displayed* Month --- #
    print(f"Fetching events for {current_calendar_month} from local database...")
    db_events = db.get_all_events(current_calendar_month)
    print(f"Found {len(db_events)} events in the database for {current_month}/{current_year}.")

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
    print(f"Fetching events for *today* ({today_date}) for the right panel...")
    today_events_db = events_by_day.get(today_date.day, [])
    today_events_db.sort(key=lambda x: (x['all_day'], x['start_datetime']))
    print(f"Found {len(today_events_db)} events for today.")

    # Get month name for the *displayed* month
    month_name = calendar.month_name[current_month]

    # Render the template with the structured data
    return render_template(
        'index.html', 
        weeks=weeks_data, 
        today_events=today_events_db,
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
