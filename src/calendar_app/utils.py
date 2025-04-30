from .models import CalendarEvent
from . import database as db 
from .database import db_connection 

@db_connection 
def add_events(cursor, events: list[CalendarEvent]): 
    """
    Checks the sqlite database for existing events adds new events to the database.
    """
    for event in events:
        existing_event = db.check_event_exists(event.id) 
        if not existing_event:
            db.add_event(event)
        else:
            # If the event already exists, update it if necessary
            # Basic check: if any attribute differs, update the whole event
            needs_update = False
            for attr, value in event.__dict__.items():
                # Handle potential datetime comparison issues if needed
                if getattr(existing_event, attr) != value:
                    needs_update = True
                    break
            if needs_update:
                 # Update existing_event object with new values before saving
                 for attr, value in event.__dict__.items():
                      setattr(existing_event, attr, value)
                 db.add_event(existing_event) 

def initialize_db():
    """
    Initializes the database and creates the necessary tables.
    """
    if not db.DATABASE_FILE.exists():
        # Create the database file and tables
        db.create_all()
        print(f"Database created at {db.DATABASE_FILE}")