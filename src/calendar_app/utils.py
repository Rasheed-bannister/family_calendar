from .models import CalendarEvent
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

def initialize_db():
    """
    Initializes the database and creates the necessary tables.
    """
    if not db.DATABASE_FILE.exists():
        # Create the database file and tables
        db.create_all()