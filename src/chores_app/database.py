import sqlite3
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
