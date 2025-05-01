from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import datetime
from .api import authenticate # Reuse the existing authentication

# --- Constants ---
# You might want to make the target list name configurable
TARGET_TASK_LIST_NAME = "Chores"

# --- Functions ---

def get_tasks_service():
    """Authenticates and builds the Google Tasks API service."""
    creds = authenticate()
    if not creds:
        print("Google Tasks authentication failed or skipped.")
        return None
    try:
        service = build("tasks", "v1", credentials=creds)
        return service
    except HttpError as error:
        print(f"An API error occurred building Tasks service: {error}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred building Tasks service: {e}")
        return None

def find_task_list_id(service, list_name):
    """Finds the ID of a task list by its name."""
    try:
        results = service.tasklists().list().execute() # Adjust maxResults if needed
        items = results.get('items', [])
        for item in items:
            if item['title'] == list_name:
                # print(f"Found task list '{list_name}' with ID: {item['id']}")
                return item['id']
        print(f"Task list '{list_name}' not found.")
        return None
    except HttpError as error:
        print(f"An API error occurred fetching task lists: {error}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred fetching task lists: {e}")
        return None


def fetch_tasks_from_list(service, task_list_id):
    """Fetches tasks from a specific task list."""
    if not task_list_id:
        return []
    try:
        # Fetch only tasks that are for today or earlier
        today = datetime.datetime.now().isoformat() + "Z"
        tomorrow = (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat() + "Z"
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat() + "Z"

        results = service.tasks().list(
            tasklist=task_list_id,
            dueMax=tomorrow, # Keep filtering by due date if desired
            showCompleted=True, # Include completed tasks in the API response
            showHidden=True
        ).execute()
        items = results.get('items', [])
        # print(f"Fetched {len(items)} tasks (including completed) from list ID {task_list_id}.")
        # print(items)
        # Return a list of dictionaries with task details: title, notes, status, due
        return [
            {
                'title': item.get('title'),
                'notes': item.get('notes'),
                'status': item.get('status'),
                'due': item.get('due')
            }
            for item in items if item.get('completed') is None or item.get('completed') <= tomorrow
        ]
    except HttpError as error:
        print(f"An API error occurred fetching tasks: {error}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred fetching tasks: {e}")
        return []

def get_chores():
    """Fetches tasks from the target chore list."""
    service = get_tasks_service()
    if not service:
        return [] # Return empty list if service failed

    task_list_id = find_task_list_id(service, TARGET_TASK_LIST_NAME)
    if not task_list_id:
        return [] # Return empty list if list not found

    chores = fetch_tasks_from_list(service, task_list_id)
    return chores


