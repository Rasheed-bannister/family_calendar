from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import datetime
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

TARGET_TASK_LIST_NAME = "Chores"

# Define separate scopes for tasks - includes write permission
TASKS_SCOPES = ["https://www.googleapis.com/auth/tasks"]

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

    # The file tasks_token.json stores the user's access and refresh tokens
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, TASKS_SCOPES)
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing tasks token: {e}")
                creds = None  # Reset creds to trigger the flow below
        
        # Only run the flow if creds are still None
        if not creds:
            if not os.path.exists(creds_path):
                print(f"Error: Credentials file not found at {creds_path}")
                print("Please download your credentials file from Google Cloud Console and place it there.")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, TASKS_SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"Error during tasks authentication flow: {e}")
                return None

        # Save the credentials for the next run
        if creds:
            try:
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            except IOError as e:
                print(f"Error saving tasks token file: {e}")
    
    return creds

def get_tasks_service():
    """Authenticates and builds the Google Tasks API service."""
    creds = authenticate_tasks()
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
        results = service.tasklists().list().execute()
        items = results.get('items', [])
        for item in items:
            if item['title'] == list_name:
                return item['id']
        print(f"Task list '{list_name}' not found.")
        return None
    except HttpError as error:
        print(f"An API error occurred fetching task lists: {error}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred fetching task lists: {e}")
        return None


def fetch_tasks_from_list(service, task_list_id) -> list[dict]:
    """Fetches tasks from a specific task list."""
    if not task_list_id:
        return []
    try:
        today = datetime.datetime.now().isoformat() + "Z"
        tomorrow = (datetime.datetime.now() + datetime.timedelta(days=2)).isoformat() + "Z"
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat() + "Z"

        results = service.tasks().list(
            tasklist=task_list_id,
            dueMax=tomorrow,
            showCompleted=True, # Include completed tasks in the API response
            showHidden=True
        ).execute()
        items = results.get('items', [])
        
        return [
            {
                'id': item.get('id'),
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
        # First get the current task to preserve any fields not in updates
        service = get_tasks_service()
        current_task = service.tasks().get(
            tasklist=task_list_id,
            task=chore_id
        ).execute()
        
        # Apply updates
        for key, value in updates.items():
            current_task[key] = value
        
        # Update the task
        result = service.tasks().update(
            tasklist=task_list_id,
            task=chore_id,
            body=current_task
        ).execute()
        
        return True
    except HttpError as error:
        print(f"An API error occurred updating task: {error}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred updating task: {e}")
        return False

def mark_chore_completed(chore_id):
    """Marks a chore as completed."""
    return update_chore(chore_id, updates={
        'status': 'completed',
        'completed': datetime.datetime.utcnow().isoformat() + "Z"
    })


