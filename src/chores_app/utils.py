from . import database as db  # Import the database module
from .models import Chore


def initialize_db():
    """Checks if the chores database exists and creates it if not."""
    if not db.DATABASE_FILE.exists():
        print("Chores database not found. Creating...")
        db.create_all()
        print("Chores database created.")


def create_chores_from_google_data(google_tasks_data: list[dict]) -> list[Chore]:
    """Processes raw Google Tasks data and converts it into a list of Chore objects."""
    chores_to_add = []
    if not google_tasks_data:
        return chores_to_add

    for task in google_tasks_data:
        # Assuming the 'title' contains the assigned person and 'notes' the description
        chore = Chore(
            id=task.get("id"),
            title=task.get("title", "Unassigned"),  # Default if title is missing
            notes=task.get("notes", ""),  # Default if notes are missing
            status=task.get("status"),
            due=task.get("due"),
        )
        chores_to_add.append(chore)
    return chores_to_add
