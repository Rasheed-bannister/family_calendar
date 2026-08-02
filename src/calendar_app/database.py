import datetime
import logging
import sqlite3
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from src.config import get_month_bounds

from .models import Calendar, CalendarEvent, CalendarMonth

logger = logging.getLogger(__name__)

DATABASE_FILE = Path(__file__).parent / "calendar.db"

# How long a connection waits for a writer to release its lock before giving up.
# The background sync thread writes a month at a time while the display thread
# reads; on an SD card a write can take long enough that a reader without a
# busy timeout fails instantly with "database is locked".
BUSY_TIMEOUT_MS = 5000

# Indexes are declared here rather than inline in create_all so run_migrations
# can apply the same set to databases that predate them. Each entry is a single
# CREATE INDEX statement, applied independently so one failure cannot cost the
# others (see _create_indexes).
_INDEXES = (
    # cleanup_deleted_events and get_all_events both filter CalendarEvent by
    # month_id; without this every month view scans the whole event table.
    "CREATE INDEX IF NOT EXISTS idx_calendarevent_month_id "
    "ON CalendarEvent(month_id)",
    # get_all_events_for_month_range filters on `datetime(start_datetime) <= ?`
    # and sorts by `datetime(start_datetime)`. The index has to be over the same
    # expression the query uses - a plain index on the raw column cannot serve a
    # function-wrapped comparison - and it removes the ORDER BY sort as well.
    "CREATE INDEX IF NOT EXISTS idx_calendarevent_start_datetime "
    "ON CalendarEvent(datetime(start_datetime))",
)

# Default colors list
DEFAULT_COLORS = [
    "#3D5A80",
    "#8336E7",
    "#616042",
    "#CD3813",
    "#293241",
    "#9D4348",
    "#088745",
    "#68710A",
    "#A84710",
    "#EE1B49",
]


def _apply_pragmas(conn) -> None:
    """Put a fresh connection into the mode this app needs.

    WAL lets the display keep reading while the sync thread writes, instead of
    the two blocking each other; it is stored in the database header, so this is
    a no-op after the first connection but stays correct for a database created
    before WAL was introduced here. ``synchronous=NORMAL`` is the standard
    companion to WAL - durable across process crashes, and it spares an SD card
    an fsync per commit.

    Failing to set a pragma is not fatal (an older SQLite, a read-only mount):
    the app works without them, just less happily under concurrency.

    ``foreign_keys`` is deliberately left off. The schema declares foreign keys
    but they have never been enforced, and get_all_events LEFT JOINs Calendar
    precisely because events with a missing calendar row exist in the wild;
    turning enforcement on here would start rejecting those writes.
    """
    try:
        # Set the busy timeout first so the journal_mode switch itself waits for
        # a concurrent writer rather than failing.
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error as e:
        logger.warning("Could not apply SQLite pragmas: %s", e)


@contextmanager
def _cursor_scope(commit: bool):
    """Yields a cursor for DATABASE_FILE and guarantees the connection closes.

    On success the transaction is committed (unless ``commit=False``); on any
    exception it is rolled back and the exception is re-raised, so callers can
    tell a failure apart from an empty result. The connection is closed in a
    ``finally`` block either way.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    _apply_pragmas(conn)
    try:
        yield conn.cursor()
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_connection(func=None, *, commit: bool = True):
    """Scoped database cursor, usable as a context manager or as a decorator.

        with db_connection() as cursor:          # preferred; matches chores_app
            ...
        with db_connection(commit=False) as cursor:   # read-only
            ...

        @db_connection                           # legacy, injects the cursor
        def add_events(cursor, events): ...

    The decorator form only exists because ``src/calendar_app/utils.py`` uses it
    on its own functions; new code should use the context manager so the cursor
    is visible at the call site.

    Errors are no longer swallowed. This used to log a ``sqlite3.Error`` and
    return ``[]`` from whatever function raised it, which made a failed read
    indistinguishable from an empty one: ``get_calendar`` answered "no such
    calendar" when the database was simply unreachable, and its caller in
    utils.py duly created a duplicate. Failures now propagate.

    Note the decorator form is spelled ``@db_connection``, never
    ``@db_connection()`` - the latter would hand back a context manager.
    """
    if callable(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            with _cursor_scope(commit=commit) as cursor:
                return func(cursor, *args, **kwargs)

        return wrapper

    return _cursor_scope(commit=commit)


def serialize_datetime(value: datetime.datetime) -> str:
    """Render an event timestamp for storage in CalendarEvent.

    Offsets are preserved rather than converted to UTC on purpose: the view
    layer calls ``.date()`` / ``strftime()`` straight off the parsed value to
    decide which day cell an event belongs in and what time to print, so
    rewriting rows into UTC would move every evening event a day forward.
    A naive value is stamped as UTC, which is the convention both
    ``datetime()`` in SQLite and the view's reader already assume, so stored
    timestamps are always explicitly offset-qualified.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.isoformat()


def _create_indexes(cursor) -> None:
    """Create the indexes the queries in this module depend on.

    Every statement is ``IF NOT EXISTS`` so this is safe to re-run, and each one
    is attempted separately: an index the local SQLite will not accept must not
    take the others down with it, since a rollback would discard the whole batch.
    """
    for statement in _INDEXES:
        try:
            cursor.execute(statement)
        except sqlite3.Error as e:
            logger.warning("Could not create index (%s): %s", statement, e)


def create_all():
    """
    Creates the necessary tables in the database.

    Safe to call unconditionally: SQLite creates the file itself on connect and
    every statement is ``IF NOT EXISTS``, so an existing database is left alone.
    This used to truncate DATABASE_FILE with ``open(..., "w")`` first, which
    destroyed every event in an existing database.
    """
    with db_connection() as cursor:
        # Create Calendar table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Calendar (
                calendar_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                display_name TEXT,
                color TEXT
            )
        """)

        # Create CalendarMonth table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS CalendarMonth (
                id TEXT PRIMARY KEY,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL
            )
        """)

        # Create CalendarEvent table
        cursor.execute("""
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
        """)

        # Create DefaultColors table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS DefaultColors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hex_code TEXT NOT NULL UNIQUE
            )
        """)

        # Create ColorIndex table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ColorIndex (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                current_index INTEGER NOT NULL DEFAULT 0
            )
        """)

        _create_indexes(cursor)

        # Populate DefaultColors if empty
        cursor.execute("SELECT COUNT(*) FROM DefaultColors")
        if cursor.fetchone()[0] == 0:
            cursor.executemany(
                "INSERT INTO DefaultColors (hex_code) VALUES (?)",
                [(color,) for color in DEFAULT_COLORS],
            )

        # Initialize ColorIndex if empty
        cursor.execute("SELECT COUNT(*) FROM ColorIndex")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO ColorIndex (id, current_index) VALUES (1, 0)")


def _migrate_display_name(cursor) -> None:
    """Add Calendar.display_name to databases created before aliases existed."""
    cursor.execute("PRAGMA table_info(Calendar)")
    columns = [column[1] for column in cursor.fetchall()]

    if "display_name" not in columns:
        logger.info("Adding display_name column to Calendar table...")
        cursor.execute("ALTER TABLE Calendar ADD COLUMN display_name TEXT")
        logger.info("Migration complete: display_name column added")


def run_migrations():
    """Bring an existing database up to the current schema.

    Each step runs in its own transaction so a step that fails cannot roll back
    the work of an earlier one, and a failure is logged rather than raised:
    migrations run from ``initialize_db`` during app startup, and a database
    that cannot be migrated is still worth serving from.
    """
    steps = (
        _migrate_display_name,
        _repair_unparseable_event_timestamps,
        _create_indexes,
    )

    for step in steps:
        try:
            with db_connection() as cursor:
                step(cursor)
        except sqlite3.Error as e:
            logger.error(
                "Migration step %s failed: %s", step.__name__, e, exc_info=True
            )


def _repair_unparseable_event_timestamps(cursor) -> int:
    """Rewrite event timestamps SQLite cannot interpret as instants.

    ``get_all_events_for_month_range`` compares timestamps through SQLite's
    ``datetime()``, which yields NULL for anything it cannot parse - such a row
    would silently vanish from the month view. Existing databases hold rows
    written with assorted UTC offsets; those parse fine, but this repairs any
    stragglers rather than letting them disappear.

    Rows are only rewritten when Python can re-parse them, so nothing is ever
    dropped or guessed at: an unrecoverable value is logged and left untouched.
    """
    try:
        cursor.execute("""
            SELECT id, start_datetime, end_datetime FROM CalendarEvent
            WHERE datetime(start_datetime) IS NULL OR datetime(end_datetime) IS NULL
        """)
        broken_rows = cursor.fetchall()
    except sqlite3.Error as e:
        logger.warning("Could not scan for unparseable event timestamps: %s", e)
        return 0

    repaired = 0
    for event_id, raw_start, raw_end in broken_rows:
        try:
            start = datetime.datetime.fromisoformat(raw_start)
            end = datetime.datetime.fromisoformat(raw_end)
        except (TypeError, ValueError):
            logger.warning(
                "Event %s has timestamps that cannot be parsed (%r / %r); "
                "leaving the row untouched",
                event_id,
                raw_start,
                raw_end,
            )
            continue

        cursor.execute(
            "UPDATE CalendarEvent SET start_datetime = ?, end_datetime = ? WHERE id = ?",
            (serialize_datetime(start), serialize_datetime(end), event_id),
        )
        repaired += 1

    if repaired:
        logger.info("Migration complete: normalized %d event timestamp(s)", repaired)

    return repaired


def add_calendar(calendar: Calendar):
    """Adds or replaces a Calendar in the database."""
    with db_connection() as cursor:
        if calendar.color is None:
            calendar.color = get_next_color(cursor)

        cursor.execute(
            """
            INSERT OR REPLACE INTO Calendar (calendar_id, name, display_name, color)
            VALUES (?, ?, ?, ?)
        """,
            (
                calendar.calendar_id,
                calendar.name,
                calendar.display_name,
                calendar.color,
            ),
        )


def get_calendar(calendar_id: str) -> Calendar | None:
    """Returns the stored Calendar, or None when there is no such row.

    ``None`` means "not stored". A database failure raises rather than
    masquerading as a missing calendar - callers create a calendar when this
    returns falsy, so the two must not look alike.
    """
    with db_connection(commit=False) as cursor:
        cursor.execute(
            "SELECT calendar_id, name, display_name, color FROM Calendar WHERE calendar_id = ?",
            (calendar_id,),
        )
        row = cursor.fetchone()

    if row:
        return Calendar(
            calendar_id=row[0], name=row[1], display_name=row[2], color_hex=row[3]
        )
    return None


def add_month(month: CalendarMonth):
    """Adds or replaces a CalendarMonth in the database."""
    with db_connection() as cursor:
        cursor.execute(
            """
            INSERT OR REPLACE INTO CalendarMonth (id, year, month)
            VALUES (?, ?, ?)
        """,
            (month.id, month.year, month.month),
        )


def get_month(month_id: str) -> CalendarMonth | None:
    """Retrieves a CalendarMonth by its ID, or None if it is not stored."""
    with db_connection(commit=False) as cursor:
        cursor.execute(
            "SELECT id, year, month FROM CalendarMonth WHERE id = ?", (month_id,)
        )
        row = cursor.fetchone()

    if row:
        return CalendarMonth(year=row[1], month=row[2])  # id is derived in constructor
    return None


def add_event(event: CalendarEvent):
    """
    Adds a CalendarEvent to the database.
    """
    with db_connection() as cursor:
        # Insert or replace the event
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
                event.month.id,  # Corrected: Use month_id
                event.title,
                serialize_datetime(event.start),
                serialize_datetime(event.end),
                event.all_day,
                event.location,
                event.description,
            ),
        )


def get_all_events(month: CalendarMonth) -> list[dict]:
    """
    Retrieves all events for a specific month from the database.
    Returns a list of dictionaries, including the event ID as 'google_event_id'.
    Uses LEFT JOIN to include events even if their calendar entry is missing.

    An empty list means the month holds no events; a database failure raises.
    """
    with db_connection(commit=False) as cursor:
        cursor.execute(
            """
            SELECT distinct
                ev.id,
                ev.title,
                ev.start_datetime,
                ev.end_datetime,
                ev.all_day,
                ev.location,
                ev.description,
                COALESCE(cal.display_name, cal.name) as calendar_name,  -- Use display_name if available
                cal.color  -- Might be NULL if calendar is missing
            FROM CalendarEvent ev
                LEFT JOIN Calendar cal ON ev.calendar_id = cal.calendar_id -- Changed to LEFT JOIN
            WHERE ev.month_id = ?
        """,
            (month.id,),
        )

        rows = cursor.fetchall()

    events = []
    for row in rows:
        event = {
            "google_event_id": row[0],
            "title": row[1],
            "start_datetime": datetime.datetime.fromisoformat(row[2]),
            "end_datetime": datetime.datetime.fromisoformat(row[3]),
            "all_day": bool(row[4]),
            "location": row[5],
            "description": row[6],
            "calendar_name": (
                row[7] if row[7] else "Unknown Calendar"
            ),  # Handle potential NULL
            "calendar_color": (
                row[8] if row[8] else "#808080"
            ),  # Handle potential NULL (default grey)
        }
        events.append(event)

    return events


def get_all_events_for_month_range(year: int, month: int) -> list[dict]:
    """
    Retrieves all events that overlap with the specified month.

    The month is bounded in the configured *local* timezone, not UTC: an event
    at 22:00 on the 31st is still part of that month even though it is already
    the 1st in UTC.

    Comparisons go through SQLite's ``datetime()``, which resolves the stored
    ``+HH:MM``/``Z``/naive suffixes to a single UTC representation. Comparing
    the raw strings was wrong: rows are written with whatever offset Google
    returned (e.g. ``-04:00``), so a lexicographic test against a ``+00:00``
    literal is not an instant comparison at all. ``datetime()`` also makes the
    ordering correct across rows stored with different offsets, and it works on
    databases that already contain mixed-offset rows without rewriting them.
    """
    month_start, month_end = get_month_bounds(year, month)

    # Half-open [start, end) month window expressed in UTC for SQLite.
    start_param = month_start.astimezone(datetime.timezone.utc).isoformat()
    end_param = month_end.astimezone(datetime.timezone.utc).isoformat()

    # Two intervals overlap iff each starts before the other ends. Boundary
    # touches are kept (<=/>=) so this stays a superset of what the per-day
    # filter in the view actually renders - being over-inclusive here is free,
    # being under-inclusive loses events.
    with db_connection(commit=False) as cursor:
        cursor.execute(
            """
            SELECT distinct
                ev.id,
                ev.title,
                ev.start_datetime,
                ev.end_datetime,
                ev.all_day,
                ev.location,
                ev.description,
                COALESCE(cal.display_name, cal.name) as calendar_name,
                cal.color
            FROM CalendarEvent ev
            LEFT JOIN Calendar cal ON ev.calendar_id = cal.calendar_id
            WHERE
                datetime(ev.start_datetime) <= datetime(?)
                AND datetime(ev.end_datetime) >= datetime(?)
            ORDER BY datetime(ev.start_datetime)
        """,
            (end_param, start_param),
        )

        rows = cursor.fetchall()

    events = []
    for row in rows:
        event = {
            "google_event_id": row[0],
            "title": row[1],
            "start_datetime": datetime.datetime.fromisoformat(row[2]),
            "end_datetime": datetime.datetime.fromisoformat(row[3]),
            "all_day": bool(row[4]),
            "location": row[5],
            "description": row[6],
            "calendar_name": row[7] if row[7] else "Unknown Calendar",
            "calendar_color": row[8] if row[8] else "#808080",
        }
        events.append(event)

    return events


def get_next_color(cursor) -> str:
    """Gets the next default color from the database and increments the index."""
    # Get current index and total number of colors
    cursor.execute("SELECT current_index FROM ColorIndex WHERE id = 1")
    current_index = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM DefaultColors")
    color_count = cursor.fetchone()[0]

    if color_count == 0:
        return "#000000"  # Default to black

    # Get the color at the current index (use 1-based index for DB query)
    # The modulo is applied *before* fetching to handle wrap-around correctly
    effective_index = current_index % color_count
    cursor.execute(
        "SELECT hex_code FROM DefaultColors WHERE id = ?", (effective_index + 1,)
    )
    color_hex = cursor.fetchone()[0]

    # Increment and update the index
    next_index = current_index + 1  # No modulo here, let it grow
    cursor.execute(
        "UPDATE ColorIndex SET current_index = ? WHERE id = 1", (next_index,)
    )

    return color_hex
