import sqlite3
from .models import CalendarEvent, CalendarMonth, Calendar
from pathlib import Path
import datetime

DATABASE_FILE = Path(__file__).parent / "calendar.db"

# Default colors list
DEFAULT_COLORS = [
    "#FF5733", "#33FF57", "#3357FF", "#FF33A1", "#A133FF",
    "#FFC300", "#DAF7A6", "#581845", "#900C3F", "#C70039"
]

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
            # Return an empty list in case of error for functions expecting lists
            return []
        finally:
            conn.close()
    return wrapper


def create_all():
    """
    Creates the necessary tables in the database.
    This function is called only when it's confirmed that there is no database file.
    """
    # Create the database file in the file system
    with open(DATABASE_FILE, 'w') as db_file:
        pass

    conn = sqlite3.connect(DATABASE_FILE)
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

    # Create DefaultColors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS DefaultColors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hex_code TEXT NOT NULL UNIQUE
        )
    ''')

    # Create ColorIndex table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ColorIndex (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_index INTEGER NOT NULL DEFAULT 0
        )
    ''')

    # Populate DefaultColors if empty
    cursor.execute('SELECT COUNT(*) FROM DefaultColors')
    if cursor.fetchone()[0] == 0:
        cursor.executemany('INSERT INTO DefaultColors (hex_code) VALUES (?)', [(color,) for color in DEFAULT_COLORS])

    # Initialize ColorIndex if empty
    cursor.execute('SELECT COUNT(*) FROM ColorIndex')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO ColorIndex (id, current_index) VALUES (1, 0)')

    conn.commit()
    conn.close()

@db_connection
def add_calendar(cursor, calendar: Calendar): 
    """Adds or replaces a Calendar in the database."""
    if calendar.color is None:
        calendar.color = get_next_color()

    cursor.execute('''
        INSERT OR REPLACE INTO Calendar (calendar_id, name, color)
        VALUES (?, ?, ?)
    ''', (calendar.calendar_id, calendar.name, calendar.color))

@db_connection
def get_calendar(cursor, calendar_id: str) -> Calendar | None: 
    cursor.execute('SELECT calendar_id, name, color FROM Calendar WHERE calendar_id = ?', (calendar_id,))
    row = cursor.fetchone()
    if row:
        return Calendar(calendar_id=row[0], name=row[1], color_hex=row[2])
    return None

@db_connection
def add_month(cursor, month: CalendarMonth):
    """Adds or replaces a CalendarMonth in the database."""
    cursor.execute('''
        INSERT OR REPLACE INTO CalendarMonth (id, year, month)
        VALUES (?, ?, ?)
    ''', (month.id, month.year, month.month))

@db_connection
def get_month(cursor, month_id: str) -> CalendarMonth | None: 
    """Retrieves a CalendarMonth by its ID."""
    cursor.execute('SELECT id, year, month FROM CalendarMonth WHERE id = ?', (month_id,))
    row = cursor.fetchone()
    if row:
        return CalendarMonth(year=row[1], month=row[2]) # id is derived in constructor
    return None


@db_connection 
def add_event(cursor, event: CalendarEvent):
    """
    Adds a CalendarEvent to the database.
    """
    # Insert or replace the event
    cursor.execute('''
        INSERT OR REPLACE INTO CalendarEvent (
            id, calendar_id, month_id,
            title, start_datetime, end_datetime,
            all_day, location, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        event.id,
        event.calendar.calendar_id,
        event.month.id, # Corrected: Use month_id
        event.title,
        event.start.isoformat(),
        event.end.isoformat(),
        event.all_day,
        event.location,
        event.description
    ))

@db_connection
def check_event_exists(cursor, event_id: str) -> CalendarEvent | None: 
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
        # Ensure month object is created correctly using year and month
        month_obj = CalendarMonth(year=row[4], month=row[5])
        event = CalendarEvent(
            id=row[0],
            calendar=Calendar(calendar_id=row[1], name=row[6], color_hex=row[7]),
            month=month_obj, 
            title=row[5],
            start_datetime=datetime.datetime.fromisoformat(row[8]), 
            end_datetime=datetime.datetime.fromisoformat(row[9]),  
            all_day=bool(row[10]), 
            location=row[11],
            description=row[12]
        )
        return event
    return None


@db_connection 
def get_all_events(cursor, month: CalendarMonth) -> list[dict]: 
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

@db_connection
def get_next_color(cursor) -> str:
    """Gets the next default color from the database and increments the index."""
    # Get current index and total number of colors
    cursor.execute('SELECT current_index FROM ColorIndex WHERE id = 1')
    current_index = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM DefaultColors')
    color_count = cursor.fetchone()[0]

    if color_count == 0:
        return "#000000" # Default to black

    # Get the color at the current index (use 1-based index for DB query)
    # The modulo is applied *before* fetching to handle wrap-around correctly
    effective_index = current_index % color_count
    cursor.execute('SELECT hex_code FROM DefaultColors WHERE id = ?', (effective_index + 1,))
    color_hex = cursor.fetchone()[0]

    # Increment and update the index
    next_index = (current_index + 1) # No modulo here, let it grow
    cursor.execute('UPDATE ColorIndex SET current_index = ? WHERE id = 1', (next_index,))

    return color_hex