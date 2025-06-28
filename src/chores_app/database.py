import sqlite3
import uuid  # Add this import for generating UUIDs
from .models import Chore
from pathlib import Path
import datetime

DATABASE_FILE = Path(__file__).parent / "chores.db"

def create_all():
    """
    Creates the necessary tables in the database.
    This function is called only when it's confirmed that there is no database file.
    """
    # Create the database file in the file system
    with open(DATABASE_FILE, 'w'):
        pass

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Create Chores table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Chores (
            id TEXT PRIMARY KEY,
            assigned_to TEXT NOT NULL,
            description TEXT,
            status TEXT,
            due TEXT
        )
    ''')

    conn.commit()
    conn.close()

def update_chore_status(chore_id: str, new_status: str):
    """Updates the status of a specific chore in the database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE Chores
        SET status = ?
        WHERE id = ?
    ''', (new_status, chore_id))
    conn.commit()
    conn.close()

def add_chores(chores: list[Chore]):
    """
    Adds a list of chores to the database, or replaces existing ones if they have the same ID,
    unless the existing chore has status 'invisible'.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    for chore in chores:
        # Check current status before potentially overwriting
        cursor.execute('SELECT status FROM Chores WHERE id = ?', (chore.id,))
        result = cursor.fetchone()
        current_status = result[0] if result else None

        # Only insert/replace if the current status is not 'invisible'
        if current_status != 'invisible':
            cursor.execute('''
                INSERT OR REPLACE INTO Chores (id, assigned_to, description, status, due)
                VALUES (?, ?, ?, ?, ?)
            ''', (chore.id, chore.assigned_to, chore.description, chore.status, chore.due))

    conn.commit()
    conn.close()

def add_chore(assigned_to: str, description: str, status: str = 'needsAction', due: str = None, google_id: str = None) -> Chore:
    """
    Adds a single chore to the database.
    Generates a new UUID for the local ID if one isn't provided (e.g., from Google Tasks).
    Returns the created Chore object.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

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
        status=status,
        due=due
    )

    try:
        cursor.execute('''
            INSERT INTO Chores (id, assigned_to, description, status, due)
            VALUES (?, ?, ?, ?, ?)
        ''', (new_chore.id, new_chore.assigned_to, new_chore.description, new_chore.status, new_chore.due))
        conn.commit()
        print(f"Chore '{new_chore.description}' for '{new_chore.assigned_to}' added to local DB with ID: {new_chore.id}")
        return new_chore
    except sqlite3.IntegrityError as e:
        print(f"Error adding chore to DB (ID: {new_chore.id}): {e}. Chore might already exist.")
        conn.rollback()
        # Depending on desired behavior, could try to fetch existing chore or raise error
        # For now, returning None to indicate failure to add as new
        return None # Or raise e to indicate a more critical failure
    finally:
        conn.close()

def update_chore_google_id(local_chore_id: str, google_task_id: str):
    """Updates a locally created chore with its corresponding Google Task ID."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM Chores WHERE id = ?", (google_task_id,))
        existing_with_google_id = cursor.fetchone()

        if existing_with_google_id and existing_with_google_id[0] != local_chore_id:
            print(f"Error: Google Task ID {google_task_id} is already associated with a different local chore ({existing_with_google_id[0]}). Cannot update chore {local_chore_id}.")
            return

        cursor.execute("SELECT assigned_to, description, status, due FROM Chores WHERE id = ?", (local_chore_id,))
        chore_data = cursor.fetchone()

        if not chore_data:
            print(f"Error: Local chore with ID {local_chore_id} not found. Cannot update with Google ID.")
            return

        if local_chore_id != google_task_id:
            cursor.execute('''
                INSERT OR REPLACE INTO Chores (id, assigned_to, description, status, due)
                VALUES (?, ?, ?, ?, ?)
            ''', (google_task_id, chore_data[0], chore_data[1], chore_data[2], chore_data[3]))
            cursor.execute("DELETE FROM Chores WHERE id = ?", (local_chore_id,))
            print(f"Chore ID updated from local {local_chore_id} to Google ID {google_task_id}")
        else:
            print(f"Chore {local_chore_id} already uses Google ID {google_task_id} or is being re-confirmed.")

        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error when updating chore with Google ID: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_chores(include_invisible=False) -> list[dict]:
    """
    Fetches chores from the database.
    By default, filters out chores with status 'invisible'.
    Set include_invisible=True to fetch all chores.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    query = 'SELECT * FROM Chores'
    if not include_invisible:
        query += ' WHERE status != ?'
        cursor.execute(query, ('invisible',))
    else:
        cursor.execute(query)
        
    rows = cursor.fetchall()

    chores = []
    for row in rows:
        chore = {
            'id': row[0],
            'title': row[1],         # the intent here is that the 'title' field of the task is the person assigned to do the chore
            'notes': row[2],         # the description of the chore
            'status': row[3],
            'due': row[4]
        }
        chores.append(chore)

    conn.close()
    return chores
