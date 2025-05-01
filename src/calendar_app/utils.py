from .models import CalendarEvent, Calendar, CalendarMonth
from . import database as db 
from .database import db_connection, add_event as db_add_event # Import the actual add_event
import sqlite3 # Import sqlite3 for error handling

@db_connection
def add_events(cursor, events: list[CalendarEvent]) -> bool:
    """
    Simplified version for debugging: Checks if event exists by ID and adds if not.
    Returns True if any events were successfully inserted.
    """
    changes_made = False
    # print(f"DEBUG: Starting simplified add_events with {len(events)} events.") # Debug print

    for event in events:
        try:
            # Check if event ID exists directly using the cursor from the decorator
            cursor.execute("SELECT 1 FROM CalendarEvent WHERE id = ?", (event.id,))
            exists = cursor.fetchone()

            if not exists:
                # print(f"DEBUG: Event {event.id} ('{event.title}') does not exist. Attempting insert.") # Debug print
                # Directly execute the insert logic (similar to db.add_event)
                # Ensure calendar exists and has a color first
                calendar_obj = event.calendar
                if not calendar_obj.color:
                     # Assign color if missing (using logic similar to db.add_calendar)
                     from .database import get_next_color # Local import for simplicity
                     calendar_obj.color = get_next_color(cursor=cursor) # Pass cursor
                     # Update calendar in DB as well
                     cursor.execute(
                         'INSERT OR REPLACE INTO Calendar (calendar_id, name, color) VALUES (?, ?, ?)',
                         (calendar_obj.calendar_id, calendar_obj.name, calendar_obj.color)
                     )

                cursor.execute(
                    '''
                    INSERT INTO CalendarEvent (
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
                # print(f"DEBUG: Successfully inserted event {event.id}.") # Debug print
            else:
                # If you want to see if updates *would* happen, add comparison here
                # For now, just log that it exists
                # print(f"DEBUG: Event {event.id} ('{event.title}') already exists. Skipping insert.") # Debug print
                pass # In this simplified version, we don't update

        except sqlite3.Error as e:
            print(f"DEBUG: Database error processing event {event.id}: {e}")
            # Optionally: return False immediately on error, or just log and continue
            continue # Continue with the next event

    # print(f"DEBUG: Finished simplified add_events. changes_made = {changes_made}") # Debug print
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

        # Get or create Calendar object
        calendar_obj = db.get_calendar(google_cal_id)
        calendar_needs_db_update = False
        if not calendar_obj:
            # Create new Calendar, color will be assigned by add_calendar
            calendar_obj = Calendar(calendar_id=google_cal_id, name=google_cal_summary)
            calendar_needs_db_update = True
            calendars_changed = True # New calendar added
        elif calendar_obj.name != google_cal_summary:
            # Update existing calendar name
            calendar_obj.name = google_cal_summary
            # Keep existing color
            calendar_needs_db_update = True
            calendars_changed = True # Calendar name changed

        if calendar_needs_db_update:
            db.add_calendar(calendar_obj)
            # Re-fetch the calendar object in case a color was assigned by add_calendar
            calendar_obj = db.get_calendar(google_cal_id)
            if not calendar_obj:
                 # Handle rare case where add/get fails unexpectedly
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