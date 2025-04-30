import datetime
import os
import calendar as pycalendar # Alias to avoid conflict with module name

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def authenticate():
  """
  Handles authentication with Google Calendar API using OAuth 2.0.

  Checks for existing valid credentials in token.json, refreshes if expired,
  or initiates the OAuth flow if no valid credentials exist.

  Returns:
      google.oauth2.credentials.Credentials: The authenticated credentials object,
                                             or None if authentication fails.
  """
  creds = None
  script_dir = os.path.dirname(__file__)
  token_path = os.path.join(script_dir, "token.json")
  creds_path = os.path.join(script_dir, "credentials.json")

  # The file token.json stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  if os.path.exists(token_path):
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
  # If there are no (valid) credentials available, let the user log in.
  if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
      try:
        creds.refresh(Request())
      except Exception as e:
        print(f"Error refreshing token: {e}")
        # Attempt re-authentication if refresh fails
        creds = None # Reset creds to trigger the flow below
    # Only run the flow if creds are still None (initial run or refresh failed)
    if not creds:
        # Ensure credentials.json exists
        if not os.path.exists(creds_path):
            print(f"Error: Credentials file not found at {creds_path}")
            print("Please download your credentials file from Google Cloud Console and place it there.")
            return None # Indicate failure
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                creds_path, SCOPES
            )
            # Note: run_local_server will open a browser for user authorization
            creds = flow.run_local_server(port=0)
        except Exception as e:
            print(f"Error during authentication flow: {e}")
            return None # Indicate failure

    # Save the credentials for the next run if successfully obtained/refreshed
    if creds:
        try:
            with open(token_path, "w") as token:
                token.write(creds.to_json())
        except IOError as e:
            print(f"Error saving token file: {e}")
            # Proceed with creds, but warn user they might need to re-auth next time
  return creds


def get_events_current_month(service, month: int, year: int):
  """
  Fetches all events for a specific month and year from all accessible calendars.

  Args:
      service: The authorized Google Calendar API service instance.
      month (int): The month (1-12).
      year (int): The year.

  Returns:
      list: A list of event dictionaries, sorted by start time,
            or an empty list if no events are found or an error occurs.
  """
  calendars = get_calendar_list(service)
  if not calendars:
      print("No calendars found or accessible.")
      return []

  # Calculate the time range for the given month and year
  # Ensure month and day have leading zeros if needed for isoformat
  start_day = 1
  end_day = pycalendar.monthrange(year, month)[1]
  time_min_dt = datetime.datetime(year, month, start_day, 0, 0, 0, tzinfo=datetime.timezone.utc)
  time_max_dt = datetime.datetime(year, month, end_day, 23, 59, 59, tzinfo=datetime.timezone.utc)
  time_min = time_min_dt.isoformat()
  time_max = time_max_dt.isoformat()

  all_events = []
  print(f"Fetching events for {time_min_dt.strftime('%B %Y')}...")

  for calendar in calendars:
    calendar_id = calendar["id"]
    print(f"  Fetching events from calendar: {calendar.get('summary', calendar_id)}")
    try:
      events_result = (
          service.events()
          .list(
              calendarId=calendar_id,
              timeMin=time_min,
              timeMax=time_max,
              singleEvents=True,
              orderBy="startTime",
          )
          .execute()
      )
      events = events_result.get("items", [])
      all_events.extend(events)
    except HttpError as error:
      # Handle cases like 404 if a calendar is listed but not accessible
      print(f"    Could not fetch events for calendar {calendar_id}: {error}")
    except Exception as e:
      print(f"    An unexpected error occurred fetching events for {calendar_id}: {e}")


  if not all_events:
    print(f"No events found for {time_min_dt.strftime('%B %Y')}.")
    return []

  # Sort all collected events by start time
  def get_start_time(event):
      # Handles both 'dateTime' and 'date' keys
      start = event["start"].get("dateTime", event["start"].get("date"))
      # Ensure 'date' strings are comparable with 'dateTime' strings
      if 'T' not in start: # It's a date string like 'YYYY-MM-DD'
          # Append a time part to make it comparable, assuming start of day UTC
           start += "T00:00:00Z"
      # Convert to datetime objects for robust comparison
      try:
          # Handle potential timezone info (Z or +HH:MM)
          if start.endswith('Z'):
              return datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
          else:
              # Attempt direct parsing, hoping it includes timezone or is naive UTC
              # This might need refinement based on actual Google API date formats
               return datetime.datetime.fromisoformat(start)
      except ValueError:
           # Fallback for unexpected formats - treat as minimum possible time?
           print(f"Warning: Could not parse start time '{start}' for event '{event.get('summary', 'N/A')}'. Using epoch.")
           return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


  all_events.sort(key=get_start_time)
  return all_events


def get_calendar_list(service):
  """
  Fetches the list of calendars accessible by the authenticated user.

  Args:
      service: The authorized Google Calendar API service instance.

  Returns:
      list: A list of calendar dictionaries, or an empty list if none are found
            or an error occurs.
  """
  try:
    print("Getting list of calendars...")
    calendar_list_result = service.calendarList().list().execute()
    calendars = calendar_list_result.get("items", [])
    if not calendars:
        print("No calendars found.")
        return []
    print(f"Found {len(calendars)} calendars.")
    return calendars
  except HttpError as error:
    print(f"An error occurred fetching calendar list: {error}")
    return []
  except Exception as e:
    print(f"An unexpected error occurred fetching calendar list: {e}")
    return []


def initialize():
  """Shows basic usage of the Google Calendar API.
  Authenticates, fetches events for the current month, and prints them.
  """
  creds = authenticate()

  if not creds:
      print("Authentication failed. Exiting.")
      return

  try:
    service = build("calendar", "v3", credentials=creds)

    # Get current month and year
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    current_month = now.month
    current_year = now.year

    # Fetch events for the current month
    # Note: get_events_current_month now handles fetching calendars internally
    monthly_events = get_events_current_month(service, current_month, current_year)

    if monthly_events:
        print(f"\nEvents for {now.strftime('%B %Y')}:")
        for event in monthly_events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            # Simple formatting for date/dateTime
            try:
                if 'T' in start: # DateTime
                    start_dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
                    start_formatted = start_dt.strftime('%Y-%m-%d %H:%M:%S %Z')
                else: # Date
                    start_dt = datetime.date.fromisoformat(start)
                    start_formatted = start_dt.strftime('%Y-%m-%d (All day)')
            except ValueError:
                start_formatted = start # Fallback to raw string if parsing fails

            print(f"{start_formatted} {event['summary']}")

  except HttpError as error:
    # Errors during service build or other API calls not caught in sub-functions
    print(f"An API error occurred: {error}")
  except Exception as e:
    print(f"An unexpected error occurred in main: {e}")