import pathlib
import sqlite3  # Import sqlite3 for error handling

from . import database as db
from .database import db_connection, get_next_color
from .models import Calendar, CalendarEvent, CalendarMonth


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
                    "INSERT OR REPLACE INTO Calendar (calendar_id, name, color) VALUES (?, ?, ?)",
                    (calendar_obj.calendar_id, calendar_obj.name, calendar_obj.color),
                )

            cursor.execute(
                """
                INSERT OR REPLACE INTO CalendarEvent (
                    id, calendar_id, month_id,
                    title, start_datetime, end_datetime,
                    all_day, location, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.calendar.calendar_id,
                    event.month.id,
                    event.title,
                    event.start.isoformat(),
                    event.end.isoformat(),
                    event.all_day,
                    event.location,
                    event.description,
                ),
            )

            changes_made = True
            processed_ids.add(event.id)

        except sqlite3.Error as e:
            print(f"Database error processing event {event.id}: {e}")
            continue  # Continue with the next event

    return changes_made


def create_calendar_events_from_google_data(
    processed_google_events_data: list[dict], current_calendar_month: CalendarMonth
) -> tuple[list[CalendarEvent], bool]:
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
        google_cal_id = event_data["calendar_id"]
        google_cal_summary = event_data["calendar_name"]

        calendar_obj = db.get_calendar(google_cal_id)
        calendar_needs_db_update = False

        # Get the display name from aliases if available
        display_name = get_calendar_display_name(google_cal_id, google_cal_summary)

        if not calendar_obj:  # Create new Calendar
            calendar_obj = Calendar(
                calendar_id=google_cal_id,
                name=google_cal_summary,
                display_name=display_name,
            )
            calendar_needs_db_update = True
            calendars_changed = True
        elif (
            calendar_obj.name != google_cal_summary
            or calendar_obj.display_name != display_name
        ):
            calendar_obj.name = google_cal_summary
            calendar_obj.display_name = display_name
            calendar_needs_db_update = True
            calendars_changed = True

        if calendar_needs_db_update:
            db.add_calendar(calendar_obj)
            # Re-fetch the calendar object in case a color was assigned by add_calendar
            calendar_obj = db.get_calendar(google_cal_id)
            if not calendar_obj:
                print(
                    f"Error: Failed to get calendar {google_cal_id} after adding/updating."
                )
                continue  # Skip this event if calendar handling failed

        # Create CalendarEvent object
        event = CalendarEvent(
            id=event_data["id"],
            calendar=calendar_obj,  # Use the fetched/created/updated Calendar object
            month=current_calendar_month,
            title=event_data["title"],
            start_datetime=event_data["start_datetime"],
            end_datetime=event_data["end_datetime"],
            all_day=event_data["all_day"],
            location=event_data.get("location"),
            description=event_data.get("description"),
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

    # Run migrations to update existing databases
    db.run_migrations()


@db_connection
def cleanup_deleted_events(
    cursor, month: int, year: int, current_google_event_ids: set
) -> bool:
    """
    Removes events from the database that no longer exist in Google Calendar for the given month.

    Args:
        month: The month to clean up
        year: The year to clean up
        current_google_event_ids: Set of event IDs currently in Google Calendar

    Returns:
        bool: True if any events were deleted, False otherwise
    """
    try:
        # Get the month_id for this month/year (format: "6.2025")
        month_id = f"{month}.{year}"

        # Find all events in database for this month
        cursor.execute(
            """
            SELECT id FROM CalendarEvent
            WHERE month_id = ?
        """,
            (month_id,),
        )

        db_event_ids = {row[0] for row in cursor.fetchall()}

        # Find events that exist in database but not in Google Calendar
        events_to_delete = db_event_ids - current_google_event_ids

        if events_to_delete:
            print(f"Cleaning up {len(events_to_delete)} deleted events from database")

            # Delete the orphaned events using safe parameterized query
            # Use executemany for completely safe deletion
            delete_query = "DELETE FROM CalendarEvent WHERE id = ?"
            cursor.executemany(
                delete_query, [(event_id,) for event_id in events_to_delete]
            )

            return True

        return False

    except sqlite3.Error as e:
        print(f"Error during event cleanup: {e}")
        return False


def load_calendar_aliases():
    """
    Load calendar aliases from calendar_aliases.conf file.
    Returns a dictionary mapping calendar_id to display_name.
    """
    aliases = {}
    config_file = pathlib.Path(__file__).parent.parent.parent / "calendar_aliases.conf"

    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if line and not line.startswith("#"):
                        if "=" in line:
                            calendar_id, display_name = line.split("=", 1)
                            aliases[calendar_id.strip()] = display_name.strip()
        except Exception as e:
            print(f"Warning: Could not load calendar aliases: {e}")

    return aliases


def get_calendar_display_name(calendar_id: str, original_name: str) -> str:
    """
    Get the display name for a calendar, checking aliases first.
    """
    aliases = load_calendar_aliases()
    return aliases.get(calendar_id, original_name)
