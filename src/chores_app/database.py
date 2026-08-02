import logging
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import Chore

logger = logging.getLogger(__name__)

DATABASE_FILE = Path(__file__).parent / "chores.db"

# Status used when a chore arrives without one (Google Tasks omits `status`
# on occasion, and `create_chores_from_google_data` passes it through as None).
DEFAULT_STATUS = "needsAction"

# Status that hides a chore from the UI without deleting it.
INVISIBLE_STATUS = "invisible"


@contextmanager
def db_connection(commit: bool = True):
    """
    Yields a cursor for DATABASE_FILE and guarantees the connection is closed.

    On success the transaction is committed (unless ``commit=False``); on any
    exception it is rolled back and the exception is re-raised so callers can
    tell a failure apart from an empty result. The connection is closed in a
    ``finally`` block either way, so a locked database or a disk error cannot
    leak file descriptors on a long-running process.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        yield conn.cursor()
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_all():
    """
    Creates the necessary tables in the database.

    Safe to call unconditionally: sqlite creates the file itself on connect and
    every statement is ``IF NOT EXISTS``, so an existing database is left alone.
    """
    with db_connection() as cursor:
        # Create Chores table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Chores (
                id TEXT PRIMARY KEY,
                assigned_to TEXT NOT NULL,
                description TEXT,
                status TEXT,
                due TEXT
            )
        """)


def update_chore_status(chore_id: str, new_status: str):
    """Updates the status of a specific chore in the database."""
    with db_connection() as cursor:
        cursor.execute(
            """
            UPDATE Chores
            SET status = ?
            WHERE id = ?
        """,
            (new_status, chore_id),
        )


def add_chores(chores: list[Chore]):
    """
    Adds a list of chores to the database, or replaces existing ones if they have the same ID,
    unless the existing chore has status 'invisible'.
    """
    with db_connection() as cursor:
        for chore in chores:
            # Check current status before potentially overwriting
            cursor.execute("SELECT status FROM Chores WHERE id = ?", (chore.id,))
            result = cursor.fetchone()
            current_status = result[0] if result else None

            # Only insert/replace if the current status is not 'invisible'
            if current_status != INVISIBLE_STATUS:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO Chores (id, assigned_to, description, status, due)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        chore.id,
                        chore.assigned_to,
                        chore.description,
                        # Never persist a NULL status; see DEFAULT_STATUS.
                        chore.status or DEFAULT_STATUS,
                        chore.due,
                    ),
                )


def add_chore(
    assigned_to: str,
    description: str,
    status: str = DEFAULT_STATUS,
    due: str = None,
    google_id: str = None,
) -> Chore:
    """
    Adds a single chore to the database.
    Generates a new UUID for the local ID if one isn't provided (e.g., from Google Tasks).
    Returns the created Chore object.
    """
    # If google_id is provided, use it as the primary ID.
    # Otherwise, generate a new local UUID for the chore.
    chore_id = google_id if google_id else str(uuid.uuid4())

    # Ensure 'due' is either a valid date string or None
    if due and not isinstance(due, str):
        try:
            due = due.isoformat()
        except AttributeError:
            due = None

    new_chore = Chore(
        id=chore_id,
        title=assigned_to,  # title parameter maps to assigned_to attribute
        notes=description,  # notes parameter maps to description attribute
        status=status or DEFAULT_STATUS,
        due=due,
    )

    try:
        with db_connection() as cursor:
            cursor.execute(
                """
                INSERT INTO Chores (id, assigned_to, description, status, due)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    new_chore.id,
                    new_chore.assigned_to,
                    new_chore.description,
                    new_chore.status,
                    new_chore.due,
                ),
            )
    except sqlite3.IntegrityError as e:
        logger.error(
            "Error adding chore to DB (ID: %s): %s. Chore might already exist.",
            new_chore.id,
            e,
        )
        # Depending on desired behavior, could try to fetch existing chore or raise error
        # For now, returning None to indicate failure to add as new
        return None  # Or raise e to indicate a more critical failure

    logger.info(
        "Chore '%s' for '%s' added to local DB with ID: %s",
        new_chore.description,
        new_chore.assigned_to,
        new_chore.id,
    )
    return new_chore


def update_chore_google_id(local_chore_id: str, google_task_id: str):
    """Updates a locally created chore with its corresponding Google Task ID."""
    try:
        with db_connection() as cursor:
            cursor.execute("SELECT id FROM Chores WHERE id = ?", (google_task_id,))
            existing_with_google_id = cursor.fetchone()

            if existing_with_google_id and existing_with_google_id[0] != local_chore_id:
                logger.error(
                    "Google Task ID %s is already associated with a different local chore (%s). Cannot update chore %s.",
                    google_task_id,
                    existing_with_google_id[0],
                    local_chore_id,
                )
                return

            cursor.execute(
                "SELECT assigned_to, description, status, due FROM Chores WHERE id = ?",
                (local_chore_id,),
            )
            chore_data = cursor.fetchone()

            if not chore_data:
                logger.error(
                    "Local chore with ID %s not found. Cannot update with Google ID.",
                    local_chore_id,
                )
                return

            if local_chore_id != google_task_id:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO Chores (id, assigned_to, description, status, due)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        google_task_id,
                        chore_data[0],
                        chore_data[1],
                        chore_data[2],
                        chore_data[3],
                    ),
                )
                cursor.execute("DELETE FROM Chores WHERE id = ?", (local_chore_id,))
                logger.info(
                    "Chore ID updated from local %s to Google ID %s",
                    local_chore_id,
                    google_task_id,
                )
            else:
                logger.debug(
                    "Chore %s already uses Google ID %s",
                    local_chore_id,
                    google_task_id,
                )
    except sqlite3.Error as e:
        logger.error("Database error when updating chore with Google ID: %s", e)


def get_chores(include_invisible=False) -> list[dict]:
    """
    Fetches chores from the database.
    By default, filters out chores with status 'invisible'.
    Set include_invisible=True to fetch all chores.
    """
    # Columns are named explicitly: `SELECT *` with positional indexing below
    # would silently return wrong data if a column were ever inserted mid-table.
    query = "SELECT id, assigned_to, description, status, due FROM Chores"
    params: tuple = ()

    if not include_invisible:
        # `status != 'invisible'` alone drops NULL-status rows, because
        # `NULL != 'invisible'` evaluates to NULL rather than true in SQL.
        # A chore with no status is not invisible, so it must be returned.
        query += " WHERE status IS NULL OR status != ?"
        params = (INVISIBLE_STATUS,)

    with db_connection(commit=False) as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            # the intent here is that the 'title' field of the task is the
            # person assigned to do the chore
            "title": row[1],
            "notes": row[2],  # the description of the chore
            "status": row[3],
            "due": row[4],
        }
        for row in rows
    ]
