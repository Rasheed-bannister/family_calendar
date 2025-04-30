from .models import CalendarEvent, CalendarMonth
from pathlib import Path
import database as db

@db.db_connection
def add_events(events: list[CalendarEvent]):
    """
    Checks the sqlite database for existing events adds new events to the database.
    """
    for event in events:
        existing_event = db.check_event_exists(event.id)
        if not existing_event:
            db.add_event(event)
        else:
            # If the event already exists, update it if necessary
            for attr, value in event.__dict__.items():
                if getattr(existing_event, attr) != value:
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