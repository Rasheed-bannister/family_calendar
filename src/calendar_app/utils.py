from .models import CalendarEvent, Calendar, CalendarMonth
from . import database as db 
from .database import db_connection 

@db_connection 
def add_events(cursor, events: list[CalendarEvent]) -> bool: 
    """
    Checks the sqlite database for existing events adds new events to the database.
    
    Returns:
        bool: True if any events were added or updated, False otherwise.
    """
    changes_made = False
    
    for event in events:
        existing_event = db.check_event_exists(event.id) 
        if not existing_event:
            # New event
            db.add_event(event)
            changes_made = True
        else:
            # If the event already exists, update it if necessary
            # Check specific attributes that we care about for equality
            needs_update = False
            
            # Compare relevant attributes directly instead of using __dict__
            # which can contain objects that don't compare well
            if (existing_event.title != event.title or
                existing_event.start != event.start or
                existing_event.end != event.end or
                existing_event.all_day != event.all_day or
                existing_event.location != event.location or
                existing_event.description != event.description or
                existing_event.calendar.calendar_id != event.calendar.calendar_id or
                existing_event.calendar.name != event.calendar.name or
                existing_event.calendar.color != event.calendar.color):
                
                needs_update = True
                
            if needs_update:
                 # Update existing_event object with new values before saving
                 existing_event.title = event.title
                 existing_event.start = event.start
                 existing_event.end = event.end
                 existing_event.all_day = event.all_day
                 existing_event.location = event.location
                 existing_event.description = event.description
                 # Update calendar info if needed
                 existing_event.calendar = event.calendar
                 
                 db.add_event(existing_event)
                 changes_made = True
    
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