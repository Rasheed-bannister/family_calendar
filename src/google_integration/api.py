import calendar as pycalendar
import datetime
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Calendar API now only uses read-only scope
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def parse_google_datetime(google_date_obj):
    """Parses Google API's date or dateTime object into a timezone-aware datetime."""
    dt_str = google_date_obj.get("dateTime", google_date_obj.get("date"))
    is_all_day = "dateTime" not in google_date_obj

    if is_all_day:
        # For all-day events, Google provides 'YYYY-MM-DD'
        # Represent as start of the day UTC
        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d").replace(
            tzinfo=datetime.timezone.utc
        )
    else:
        # For specific time events, Google provides RFC3339 format
        try:
            # Handle 'Z' for UTC explicitly
            if dt_str.endswith("Z"):
                dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            else:
                dt = datetime.datetime.fromisoformat(dt_str)
            # Ensure timezone-aware (assume UTC if naive, though Google API usually provides offset)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            print(f"Warning: Could not parse datetime string '{dt_str}'. Using epoch.")
            # Use min datetime with UTC timezone as a fallback
            dt = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    return dt, is_all_day


def authenticate_calendar():
    """
    Handles authentication with Google Calendar API using OAuth 2.0.

    Checks for existing valid credentials in calendar_token.json, refreshes if expired,
    or initiates the OAuth flow if no valid credentials exist.

    Returns:
        google.oauth2.credentials.Credentials: The authenticated credentials object,
                                               or None if authentication fails.
    """
    creds = None
    script_dir = os.path.dirname(__file__)
    token_path = os.path.join(script_dir, "calendar_token.json")
    creds_path = os.path.join(script_dir, "credentials.json")

    # The file calendar_token.json stores the user's access and refresh tokens
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, CALENDAR_SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing calendar token: {e}")
                # Attempt re-authentication if refresh fails
                creds = None  # Reset creds to trigger the flow below

        # Only run the flow if creds are still None (initial run or refresh failed)
        if not creds:
            if not os.path.exists(creds_path):
                print(f"Error: Credentials file not found at {creds_path}")
                print(
                    "Please download your credentials file from Google Cloud Console and place it there."
                )
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, CALENDAR_SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"Error during calendar authentication flow: {e}")
                return None

        # Save the credentials for the next run if successfully obtained/refreshed
        if creds:
            try:
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            except IOError as e:
                print(f"Error saving calendar token file: {e}")

    return creds


def get_calendar_service():
    """Authenticates and builds the Google Calendar API service."""
    creds = authenticate_calendar()
    if not creds:
        print("Google Calendar authentication failed or skipped.")
        return None
    try:
        service = build("calendar", "v3", credentials=creds)
        return service
    except HttpError as error:
        print(f"An API error occurred building Calendar service: {error}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred building Calendar service: {e}")
        return None


def get_events_current_month(service, month: int, year: int):
    """
    Fetches all events for a specific month and year from all accessible calendars,
    handling pagination.

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
        print("No calendars found or error fetching calendar list.")
        return []

    # Calculate the time range for the given month and year
    start_day = 1
    end_day = pycalendar.monthrange(year, month)[1]
    time_min_dt = datetime.datetime(
        year, month, start_day, 0, 0, 0, tzinfo=datetime.timezone.utc
    )
    time_max_dt = datetime.datetime(
        year, month, end_day, 23, 59, 59, tzinfo=datetime.timezone.utc
    )
    time_min = time_min_dt.isoformat()
    time_max = time_max_dt.isoformat()

    all_events = []

    for calendar in calendars:
        calendar_id = calendar["id"]
        calendar_summary = calendar.get("summary", calendar_id)
        page_token = None
        page_count = 0
        while True:
            page_count += 1
            try:
                events_result = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                        pageToken=page_token,
                        maxResults=250,
                    )
                    .execute()
                )
                events = events_result.get("items", [])
                all_events.extend(events)

                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break

            except HttpError as error:
                # Handle cases like 404 if a calendar is listed but not accessible
                print(
                    f"    Could not fetch events for calendar {calendar_id} (Page {page_count}): {error}"
                )
                break
            except Exception as e:
                print(
                    f"    An unexpected error occurred fetching events for {calendar_id} (Page {page_count}): {e}"
                )
                break

    if not all_events:
        return []

    # Sort all collected events by start time
    def get_start_time(event):
        # Handles both 'dateTime' and 'date' keys
        start = event["start"].get("dateTime", event["start"].get("date"))
        # Ensure 'date' strings are comparable with 'dateTime' strings
        if "T" not in start:  # It's a date string like 'YYYY-MM-DD'
            # Append a time part to make it comparable, assuming start of day UTC
            start += "T00:00:00Z"
        # Convert to datetime objects for robust comparison
        try:
            # Handle potential timezone info (Z or +HH:MM)
            if start.endswith("Z"):
                return datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
            else:
                # Attempt direct parsing, hoping it includes timezone or is naive UTC
                dt = datetime.datetime.fromisoformat(start)
                # If naive, assume UTC (though Google usually provides offset)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt
        except ValueError:
            # Fallback for unexpected formats - treat as minimum possible time?
            print(
                f"Warning: Could not parse start time '{start}' for event '{event.get('summary', 'N/A')}'. Using epoch."
            )
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
        calendar_list_result = service.calendarList().list().execute()
        calendars = calendar_list_result.get("items", [])
        if not calendars:
            return []
        return calendars
    except HttpError as error:
        print(f"An error occurred fetching calendar list: {error}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred fetching calendar list: {e}")
        return []


def fetch_and_process_google_events(month: int, year: int) -> list[dict]:
    """
    Fetches events from Google Calendar for a given month/year, processes them,
    and returns a list of dictionaries ready for database insertion.

    Returns:
        list[dict]: A list of processed event dictionaries, or an empty list on error/no events.
                    Each dictionary contains keys like 'id', 'calendar_id', 'calendar_name',
                    'title', 'start_datetime', 'end_datetime', 'all_day', 'location', 'description'.
    """
    service = get_calendar_service()
    if not service:
        return []

    processed_events = []
    try:
        google_events_raw = get_events_current_month(service, month, year)

        if not google_events_raw:
            return []

        for event_data in google_events_raw:
            google_cal_id = event_data.get("organizer", {}).get("email", "primary")
            google_cal_summary = event_data.get("organizer", {}).get(
                "displayName", google_cal_id
            )

            start_datetime, start_all_day = parse_google_datetime(event_data["start"])
            end_datetime, end_all_day = parse_google_datetime(event_data["end"])
            is_all_day = start_all_day  # Use start_all_day as the definitive flag

            processed_event = {
                "id": event_data["id"],
                "calendar_id": google_cal_id,
                "calendar_name": google_cal_summary,
                "title": event_data.get("summary", "(No Title)"),
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "all_day": is_all_day,
                "location": event_data.get("location"),
                "description": event_data.get("description"),
            }
            processed_events.append(processed_event)

    except HttpError as error:
        print(f"An API error occurred: {error}")
        return []  # Return empty list on API error
    except Exception as e:
        print(
            f"An unexpected error occurred during Google API interaction: {e}"
        )  # Keep error prints
        return []  # Return empty list on other errors

    return processed_events
