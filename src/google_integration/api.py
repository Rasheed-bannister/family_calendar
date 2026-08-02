import datetime
import logging
import os
import threading
import time
from typing import NamedTuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import get_month_bounds

logger = logging.getLogger(__name__)

# Calendar API now only uses read-only scope
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Thread-local storage for cached service objects (#7)
_thread_local = threading.local()

# Retry configuration (#4)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1  # seconds


def _retry_on_error(func, *args, retries=MAX_RETRIES, **kwargs):
    """Execute a function with exponential backoff retry on transient errors."""
    last_error = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            # Don't retry client errors (4xx) except 429 (rate limit)
            if e.resp.status < 500 and e.resp.status != 429:
                raise
            last_error = e
            if attempt < retries - 1:
                sleep_time = RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "API call failed (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1,
                    retries,
                    sleep_time,
                    e,
                )
                time.sleep(sleep_time)
        except (ConnectionError, TimeoutError, OSError) as e:
            last_error = e
            if attempt < retries - 1:
                sleep_time = RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Network error (attempt %d/%d), retrying in %ds: %s",
                    attempt + 1,
                    retries,
                    sleep_time,
                    e,
                )
                time.sleep(sleep_time)
    raise last_error


class SourcedEvent(NamedTuple):
    """A raw Google event paired with the calendar it was actually fetched from.

    The source calendar used to be thrown away by the fetch loop, leaving
    ``fetch_and_process_google_events`` to guess it from ``organizer.email``.
    That guess names whoever *organised* the event, which is a stranger's
    address for anything you were merely invited to - so the event landed in
    its own pseudo-calendar with its own palette colour, and any
    ``calendar_aliases.conf`` entry for the real calendar silently missed it.
    """

    calendar_id: str
    calendar_name: str
    event: dict


def _calendar_identity(calendar: dict) -> tuple[str, str]:
    """Return the (id, display name) to attribute a calendar's events to.

    ``summaryOverride`` wins over ``summary`` because it is the name *this*
    user gave the calendar in their own Google Calendar UI, and it is what
    Google itself shows them. A shared calendar published as
    "Bannister Family Shared Calendar" but renamed to "Family" locally should
    read "Family" on the wall display too. ``summary`` is the owner's name for
    it, and only a sensible fallback when the user has not renamed it.
    """
    calendar_id = calendar.get("id") or "primary"
    calendar_name = (
        calendar.get("summaryOverride") or calendar.get("summary") or calendar_id
    )
    return calendar_id, calendar_name


def _calendar_precedence(calendar: dict) -> tuple[int, str]:
    """Rank a calendar for resolving an event visible on more than one of them.

    The user's primary calendar wins; otherwise calendars are ranked by id.
    Both keys are properties of the calendar itself, never of the order Google
    happened to return things in, so the winner is the same on every sync.
    """
    calendar_id, _ = _calendar_identity(calendar)
    return (0 if calendar.get("primary") else 1, calendar_id)


def _deduplicate_by_event_id(
    sourced_events: list[SourcedEvent], precedence: dict[str, tuple[int, str]]
) -> list[SourcedEvent]:
    """Keep one copy of each event id, from the highest-precedence calendar.

    Google returns the same event ``id`` from every calendar that can see it,
    and downstream ``add_events`` does an ``INSERT OR REPLACE`` keyed on that
    id. Left alone, the last calendar processed won and the event's colour
    flapped between syncs. Choosing by calendar precedence instead of arrival
    order pins the event to one calendar permanently.
    """
    best: dict[str, SourcedEvent] = {}
    unkeyed: list[SourcedEvent] = []

    for item in sourced_events:
        event_id = item.event.get("id")
        if not event_id:
            # No id to collapse on (and nothing downstream can store it
            # anyway); pass it through untouched rather than dropping it.
            unkeyed.append(item)
            continue

        incumbent = best.get(event_id)
        if incumbent is None or precedence.get(
            item.calendar_id, (2, item.calendar_id)
        ) < precedence.get(incumbent.calendar_id, (2, incumbent.calendar_id)):
            best[event_id] = item

    return list(best.values()) + unkeyed


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
            logger.warning("Could not parse datetime string '%s'. Using epoch.", dt_str)
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

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, CALENDAR_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the exception, not credential material
                logger.error("Error refreshing calendar token: %s", e)
                creds = None

        if not creds:
            if not os.path.exists(creds_path):
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs a filesystem path, not credential material
                logger.error("Credentials file not found at %s", creds_path)
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, CALENDAR_SCOPES
                )
                creds = flow.run_local_server(port=0)
            except Exception as e:
                logger.error("Error during calendar authentication flow: %s", e)
                return None

        if creds:
            try:
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
            except IOError as e:
                # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the exception, not credential material
                logger.error("Error saving calendar token file: %s", e)

    return creds


def get_calendar_service():
    """Authenticates and builds the Google Calendar API service.

    Caches the service per-thread to avoid rebuilding on every call (#7).
    """
    # Check for cached service with valid credentials
    cached = getattr(_thread_local, "calendar_service", None)
    cached_creds = getattr(_thread_local, "calendar_creds", None)
    if cached and cached_creds and cached_creds.valid:
        return cached

    creds = authenticate_calendar()
    if not creds:
        logger.warning("Google Calendar authentication failed or skipped.")
        return None
    try:
        service = build("calendar", "v3", credentials=creds)
        _thread_local.calendar_service = service
        _thread_local.calendar_creds = creds
        return service
    except HttpError as error:
        logger.error("API error building Calendar service: %s", error)
        return None
    except Exception as e:
        logger.error("Unexpected error building Calendar service: %s", e)
        return None


def get_events_current_month(service, month: int, year: int):
    """
    Fetches all events for a specific month and year from all accessible calendars,
    handling pagination.

    The query window spans the month in the configured local timezone (see
    ``src.config.get_month_bounds``), not in UTC.

    Args:
        service: The authorized Google Calendar API service instance.
        month (int): The month (1-12).
        year (int): The year.

    Returns:
        list[SourcedEvent]: One entry per event, sorted by start time, each
              pairing the raw Google event dict with the id and display name of
              the calendar it was fetched from. An event visible on several
              calendars appears once, attributed to the highest-precedence one
              (see ``_calendar_precedence``). Empty if no events are found or
              an error occurs.
    """
    calendars = get_calendar_list(service)
    if not calendars:
        logger.warning("No calendars found or error fetching calendar list.")
        return []

    # Calculate the time range for the given month and year.
    #
    # The window MUST be built in the user's local timezone. Hardcoding UTC
    # ended the window at e.g. 2026-08-31T23:59:59Z, which is only 19:59:59
    # local in America/New_York, so every event later that evening fell outside
    # August's sync and was never stored for August (it only turned up once the
    # user navigated to September). The mirror image applied at the start of the
    # month, where the window reached back into the previous month.
    #
    # timeMax is exclusive in the Google Calendar API, so the first instant of
    # the next local month is exactly the right upper bound.
    time_min_dt, time_max_dt = get_month_bounds(year, month)
    time_min = time_min_dt.isoformat()
    time_max = time_max_dt.isoformat()

    all_events: list[SourcedEvent] = []
    precedence: dict[str, tuple[int, str]] = {}

    for calendar in calendars:
        calendar_id, calendar_name = _calendar_identity(calendar)
        precedence.setdefault(calendar_id, _calendar_precedence(calendar))
        page_token = None
        page_count = 0
        while True:
            page_count += 1
            try:
                request_obj = service.events().list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                    maxResults=250,
                )
                events_result = _retry_on_error(request_obj.execute)
                events = events_result.get("items", [])
                # Pair each event with its source calendar here, while we
                # still know which calendar we asked - it is unrecoverable
                # from the event payload alone.
                all_events.extend(
                    SourcedEvent(calendar_id, calendar_name, event) for event in events
                )

                page_token = events_result.get("nextPageToken")
                if not page_token:
                    break

            except HttpError as error:
                logger.warning(
                    "Could not fetch events for calendar %s (Page %d): %s",
                    calendar_id,
                    page_count,
                    error,
                )
                break
            except Exception as e:
                logger.error(
                    "Unexpected error fetching events for %s (Page %d): %s",
                    calendar_id,
                    page_count,
                    e,
                )
                break

    if not all_events:
        return []

    all_events = _deduplicate_by_event_id(all_events, precedence)

    # Sort all collected events by start time
    def get_start_time(sourced_event):
        event = sourced_event.event
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
            logger.warning(
                "Could not parse start time '%s' for event '%s'. Using epoch.",
                start,
                event.get("summary", "N/A"),
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
        request_obj = service.calendarList().list()
        calendar_list_result = _retry_on_error(request_obj.execute)
        calendars = calendar_list_result.get("items", [])
        if not calendars:
            return []
        return calendars
    except HttpError as error:
        logger.error("Error fetching calendar list: %s", error)
        return []
    except Exception as e:
        logger.error("Unexpected error fetching calendar list: %s", e)
        return []


def fetch_and_process_google_events(month: int, year: int) -> list[dict]:
    """
    Fetches events from Google Calendar for a given month/year, processes them,
    and returns a list of dictionaries ready for database insertion.

    'calendar_id'/'calendar_name' describe the calendar the event was *read
    from*, carried through from the fetch loop - not the event's organizer.

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

        for sourced_event in google_events_raw:
            event_data = sourced_event.event
            google_cal_id = sourced_event.calendar_id
            google_cal_summary = sourced_event.calendar_name

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
        logger.error("API error fetching/processing events: %s", error)
        return []
    except Exception as e:
        logger.error("Unexpected error during Google API interaction: %s", e)
        return []

    return processed_events
