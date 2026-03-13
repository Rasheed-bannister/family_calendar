import logging

from . import database as db  # Import the database module
from .models import Chore

logger = logging.getLogger(__name__)


def initialize_db():
    """Checks if the chores database exists and creates it if not."""
    if not db.DATABASE_FILE.exists():
        logger.info("Chores database not found. Creating...")
        db.create_all()
        logger.info("Chores database created.")


def make_chores_comparable(chores_list):
    """Creates a simplified, comparable representation of the chores list."""
    if not chores_list:
        return set()

    if not isinstance(chores_list, list):
        return None

    comparable_set = set()
    for item in chores_list:
        if isinstance(item, dict):
            comparable_set.add(
                (
                    item.get("id"),
                    item.get("title"),
                    item.get("notes"),
                    item.get("status"),
                )
            )
        else:
            try:
                if (
                    hasattr(item, "id")
                    and hasattr(item, "title")
                    and hasattr(item, "notes")
                    and hasattr(item, "status")
                ):
                    comparable_set.add(
                        (
                            getattr(item, "id"),
                            getattr(item, "title"),
                            getattr(item, "notes"),
                            getattr(item, "status"),
                        )
                    )
                else:
                    comparable_set.add(str(item))
            except Exception as e:
                logger.warning("Error making chore comparable: %s", e)
    return comparable_set


def create_chores_from_google_data(google_tasks_data: list[dict]) -> list[Chore]:
    """Processes raw Google Tasks data and converts it into a list of Chore objects."""
    chores_to_add: list[Chore] = []
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
