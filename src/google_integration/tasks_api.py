import datetime
import logging
import os
import threading

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .api import _retry_on_error

logger = logging.getLogger(__name__)

TARGET_TASK_LIST_NAME = "Chores"

# Define separate scopes for tasks - includes write permission
TASKS_SCOPES = ["https://www.googleapis.com/auth/tasks"]

# Thread-local storage for cached service objects (#7)
_thread_local = threading.local()


def authenticate_tasks():
    """
    Handles authentication with Google Tasks API using OAuth 2.0.

    Returns:
        google.oauth2.credentials.Credentials: The authenticated credentials object,
                                              or None if authentication fails.
    """
    creds = None
    script_dir = os.path.dirname(__file__)
    token_path = os.path.join(script_dir, "tasks_token.json")
    creds_path = os.path.join(script_dir, "credentials.json")

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, TASKS_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.error("Error refreshing tasks token: %s", e)
                creds = None

        if not creds:
            if not os.path.exists(creds_path):
                logger.error("Credentials file not found at %s", creds_path)
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, TASKS_SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                logger.error("Error during tasks authentication flow: %s", e)
                return None

        if creds:
            try:
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            except IOError as e:
                logger.error("Error saving tasks token file: %s", e)

    return creds


def get_tasks_service():
    """Authenticates and builds the Google Tasks API service.

    Caches the service per-thread to avoid rebuilding on every call (#7).
    """
    cached = getattr(_thread_local, "tasks_service", None)
    cached_creds = getattr(_thread_local, "tasks_creds", None)
    if cached and cached_creds and cached_creds.valid:
        return cached

    creds = authenticate_tasks()
    if not creds:
        logger.warning("Google Tasks authentication failed or skipped.")
        return None
    try:
        service = build("tasks", "v1", credentials=creds)
        _thread_local.tasks_service = service
        _thread_local.tasks_creds = creds
        return service
    except HttpError as error:
        logger.error("API error building Tasks service: %s", error)
        return None
    except Exception as e:
        logger.error("Unexpected error building Tasks service: %s", e)
        return None


def find_task_list_id(service, list_name):
    """Finds the ID of a task list by its name."""
    try:
        request_obj = service.tasklists().list()
        results = _retry_on_error(request_obj.execute)
        items = results.get("items", [])
        for item in items:
            if item["title"] == list_name:
                return item["id"]
        logger.warning("Task list '%s' not found.", list_name)
        return None
    except HttpError as error:
        logger.error("API error fetching task lists: %s", error)
        return None
    except Exception as e:
        logger.error("Unexpected error fetching task lists: %s", e)
        return None


def fetch_tasks_from_list(service, task_list_id) -> list[dict]:
    """Fetches tasks from a specific task list."""
    if not task_list_id:
        return []
    try:
        request_obj = service.tasks().list(
            tasklist=task_list_id,
            showCompleted=True,
            showHidden=True,
            maxResults=100,
        )
        results = _retry_on_error(request_obj.execute)
        items = results.get("items", [])

        return [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "notes": item.get("notes"),
                "status": item.get("status"),
                "due": item.get("due"),
            }
            for item in items
        ]
    except HttpError as error:
        logger.error("API error fetching tasks: %s", error)
        return []
    except Exception as e:
        logger.error("Unexpected error fetching tasks: %s", e)
        return []


def get_chores():
    """Fetches tasks from the target chore list."""
    service = get_tasks_service()
    if not service:
        return []
    task_list_id = find_task_list_id(service, TARGET_TASK_LIST_NAME)
    if not task_list_id:
        return []

    chores = fetch_tasks_from_list(service, task_list_id)
    return chores


def update_chore(chore_id, task_list_id=None, updates=None):
    """Updates a specific task with the provided updates."""
    if not task_list_id:
        service = get_tasks_service()
        if not service:
            return False
        task_list_id = find_task_list_id(service, TARGET_TASK_LIST_NAME)
        if not task_list_id:
            return False

    if not updates:
        return False

    try:
        service = get_tasks_service()
        get_request = service.tasks().get(tasklist=task_list_id, task=chore_id)
        current_task = _retry_on_error(get_request.execute)

        for key, value in updates.items():
            current_task[key] = value

        update_request = service.tasks().update(
            tasklist=task_list_id, task=chore_id, body=current_task
        )
        _retry_on_error(update_request.execute)

        return True
    except HttpError as error:
        logger.error("API error updating task: %s", error)
        return False
    except Exception as e:
        logger.error("Unexpected error updating task: %s", e)
        return False


def mark_chore_completed(chore_id):
    """Marks a chore as completed."""
    return update_chore(
        chore_id,
        updates={
            "status": "completed",
            "completed": datetime.datetime.utcnow().isoformat() + "Z",
        },
    )


def create_chore(title, task_list_id=None, details=None):
    """Creates a new chore (task) in the specified task list."""
    service = get_tasks_service()
    if not service:
        logger.warning("Failed to get Google Tasks service.")
        return None

    if not task_list_id:
        task_list_id = find_task_list_id(service, TARGET_TASK_LIST_NAME)
        if not task_list_id:
            logger.warning("Task list '%s' not found.", TARGET_TASK_LIST_NAME)
            return None

    task_body = {
        "title": title,
        "status": "needsAction",
    }
    if details:
        task_body["notes"] = details

    try:
        insert_request = service.tasks().insert(tasklist=task_list_id, body=task_body)
        created_task = _retry_on_error(insert_request.execute)
        logger.info(
            "Task created in Google: '%s', ID: %s",
            created_task.get("title"),
            created_task.get("id"),
        )
        return created_task
    except HttpError as error:
        logger.error("API error creating Google task: %s", error)
        return None
    except Exception as e:
        logger.error("Unexpected error creating Google task: %s", e)
        return None
