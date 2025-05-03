from .models import CalendarEvent, Calendar, CalendarMonth
from . import database as db
from .database import db_connection, add_event as db_add_event, get_next_color
import sqlite3 # Import sqlite3 for error handling

@db_connection
def add_events(cursor, events: list[CalendarEvent]) -> bool:
    """
    Adds or updates events in the database using INSERT OR REPLACE.
    Returns True if any events were successfully inserted or replaced.
    """
    changes_made = False
    # Keep track of processed IDs to avoid redundant operations if duplicates exist in input
    processed_ids = set()

    for event in events:
        if event.id in processed_ids:
            continue 

        try:
            # Ensure calendar exists and has a color first
            calendar_obj = event.calendar
            if not calendar_obj.color:
                 calendar_obj.color = get_next_color(cursor=cursor)
                 cursor.execute(
                     'INSERT OR REPLACE INTO Calendar (calendar_id, name, color) VALUES (?, ?, ?)',
                     (calendar_obj.calendar_id, calendar_obj.name, calendar_obj.color)
                 )

            cursor.execute(
                '''
                INSERT OR REPLACE INTO CalendarEvent (
                    id, calendar_id, month_id,
                    title, start_datetime, end_datetime,
                    all_day, location, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    event.id,
                    event.calendar.calendar_id,
                    event.month.id,
                    event.title,
                    event.start.isoformat(),
                    event.end.isoformat(),
                    event.all_day,
                    event.location,
                    event.description
                )
            )

            changes_made = True
            processed_ids.add(event.id)

        except sqlite3.Error as e:
            print(f"DEBUG: Database error processing event {event.id}: {e}")
            continue # Continue with the next event

    return changes_made

def create_calendar_events_from_google_data(processed_google_events_data: list[dict], current_calendar_month: CalendarMonth) -> tuple[list[CalendarEvent], bool]:
    """
    Processes raw event data fetched from Google API, creates/updates necessary
    Calendar objects in the DB, creates CalendarEvent objects, and returns them.

    Args:
        processed_google_events_data (list[dict]): List of dictionaries, each representing
                                                   an event processed from Google API.
        current_calendar_month (CalendarMonth): The CalendarMonth object for these events.

    Returns:
        tuple[list[CalendarEvent], bool]: A tuple containing:
            - list[CalendarEvent]: The list of created CalendarEvent objects.
            - bool: True if any Calendar information (name, color) was added or changed,
                    False otherwise.
    """
    events_to_add_or_update = []
    calendars_changed = False

    for event_data in processed_google_events_data:
        google_cal_id = event_data['calendar_id']
        google_cal_summary = event_data['calendar_name']

        calendar_obj = db.get_calendar(google_cal_id)
        calendar_needs_db_update = False
        if not calendar_obj: # Create new Calendar
            calendar_obj = Calendar(calendar_id=google_cal_id, name=google_cal_summary)
            calendar_needs_db_update = True
            calendars_changed = True
        elif calendar_obj.name != google_cal_summary:
            calendar_obj.name = google_cal_summary
            calendar_needs_db_update = True
            calendars_changed = True

        if calendar_needs_db_update:
            db.add_calendar(calendar_obj)
            # Re-fetch the calendar object in case a color was assigned by add_calendar
            calendar_obj = db.get_calendar(google_cal_id)
            if not calendar_obj:
                 print(f"Error: Failed to get calendar {google_cal_id} after adding/updating.")
                 continue # Skip this event if calendar handling failed

        # Create CalendarEvent object
        event = CalendarEvent(
            id=event_data['id'],
            calendar=calendar_obj, # Use the fetched/created/updated Calendar object
            month=current_calendar_month,
            title=event_data['title'],
            start_datetime=event_data['start_datetime'],
            end_datetime=event_data['end_datetime'],
            all_day=event_data['all_day'],
            location=event_data.get('location'),
            description=event_data.get('description')
        )
        events_to_add_or_update.append(event)

    return events_to_add_or_update, calendars_changed


def initialize_db():
    """
    Initializes the database and creates the necessary tables.
    """
    if not db.DATABASE_FILE.exists():
        # Create the database file and tables
        db.create_all()