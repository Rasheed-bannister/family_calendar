import sqlite3
from .models import CalendarEvent, CalendarMonth, Calendar
from pathlib import Path
import datetime

DATABASE_FILE = Path(__file__).parent / "calendar.db"

# create a decorator to wrap database functions in a connection and close after use
def db_connection(func):
    def wrapper(*args, **kwargs):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        try:
            result = func(cursor, *args, **kwargs)
            conn.commit()
            return result
        except sqlite3.Error as e:
            print(f"Database error: {e}")
        finally:
            conn.close()
    return wrapper


def create_all():
    """
    Creates the necessary tables in the database.
    This function is called only when it's confirmed that there is no database file.
    """
    # Create the database file in the file system
    db_filepath = Path(__file__).parent / "calendar.db"
    with open(db_filepath, 'w') as db_file:
        pass

    conn = sqlite3.connect('calendar.db')
    cursor = conn.cursor()

    # Create Calendar table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Calendar (
            calendar_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT
        )
    ''')

    # Create CalendarMonth table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS CalendarMonth (
            id TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL
        )
    ''')

    # Create CalendarEvent table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS CalendarEvent (
            id TEXT PRIMARY KEY,
            calendar_id TEXT NOT NULL,
            month_id TEXT NOT NULL,
            title TEXT NOT NULL,
            start_datetime TEXT NOT NULL,
            end_datetime TEXT NOT NULL,
            all_day BOOLEAN NOT NULL,
            location TEXT,
            description TEXT,
            FOREIGN KEY (calendar_id) REFERENCES Calendar(calendar_id),
            FOREIGN KEY (month_id) REFERENCES CalendarMonth(id)
        )
    ''')

    conn.commit()
    conn.close()
    print("Database tables created successfully.")

def add_event(event: CalendarEvent, cursor: sqlite3.Cursor):
    """
    Adds a CalendarEvent to the database.
    """
    # Insert or replace the event
    cursor.execute('''
        INSERT OR REPLACE INTO CalendarEvent (
            id, calendar_id, month_year, month_month,
            title, start_datetime, end_datetime,
            all_day, location, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        event.id,
        event.calendar.calendar_id,
        event.month.year,
        event.month.month,
        event.title,
        event.start.isoformat(),
        event.end.isoformat(),
        event.all_day,
        event.location,
        event.description
    ))
    print(f"Event {event.title} added to the database.")

def check_event_exists(event_id: str, cursor: sqlite3.Cursor) -> CalendarEvent:
    """
    Checks if an event with the given ID exists in the database.
    """
    cursor.execute('''
        SELECT 
            ev.id,
            ev.calendar_id,
            m.id,
            m.year,
            m.month,
            ev.title,
            cal.name,
            cal.color,
            ev.start_datetime,
            ev.end_datetime,
            ev.all_day,
            ev.location,
            ev.description 
        FROM CalendarEvent ev
            JOIN Calendar cal ON ev.calendar_id = cal.calendar_id
            JOIN CalendarMonth m ON ev.month_id = m.id
        WHERE ev.id = ?
    ''', (event_id,))

    row = cursor.fetchone()
    if row:
        event = CalendarEvent(
            id=row[0],
            calendar=Calendar(calendar_id=row[1], name=row[6], color=row[7]),
            month=CalendarMonth(id=row[2], year=row[3], month=row[4]),
            title=row[5],
            start=datetime.datetime.fromisoformat(row[8]),
            end=datetime.datetime.fromisoformat(row[9]),
            all_day=row[10],
            location=row[11],
            description=row[12]
        )
        return event
    return None


def get_all_events(month: CalendarMonth, cursor: sqlite3.Cursor) -> list[dict]:
    """
    Retrieves all events for a specific month from the database.
    """
    cursor.execute('''
        SELECT distinct
            ev.title,
            ev.start_datetime,
            ev.end_datetime,
            ev.all_day,
            ev.location,
            ev.description,
            cal.name,
            cal.color 
        FROM CalendarEvent ev
            JOIN Calendar cal ON ev.calendar_id = cal.calendar_id
        WHERE ev.month_id = ?
    ''', (month.id,))

    rows = cursor.fetchall()
    events = []
    for row in rows:
        event = {
            'calendar_color': row[7],
            'calendar_name': row[6],
            'title': row[0],
            'start_datetime': datetime.datetime.fromisoformat(row[1]),
            'end_datetime': datetime.datetime.fromisoformat(row[2]),
            'all_day': row[3],
            'location': row[4],
            'description': row[5],
        }
        events.append(event)

    return events