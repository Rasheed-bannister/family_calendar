import calendar
import datetime
import threading

from flask import Blueprint, current_app, jsonify, render_template

# Shared resources
from src.main import background_tasks, google_fetch_lock

from . import database as db
from .models import CalendarMonth

# Now only importing the calendar API


calendar_bp = Blueprint("calendar", __name__, url_prefix="/calendar")


def _calculate_navigation_dates(
    current_year: int, current_month: int
) -> tuple[int, int, int, int]:
    """Calculate previous and next month/year for calendar navigation."""
    first_day_of_current_month = datetime.date(current_year, current_month, 1)
    prev_month_date = first_day_of_current_month - datetime.timedelta(days=1)
    prev_month = prev_month_date.month
    prev_year = prev_month_date.year

    if current_month == 12:
        next_month = 1
        next_year = current_year + 1
    else:
        next_month = current_month + 1
        next_year = current_year

    return prev_year, prev_month, next_year, next_month


def _should_start_calendar_background_task(task_id: str) -> bool:
    """Check if calendar background task should be started or refreshed."""
    with google_fetch_lock:
        task_info = background_tasks.get(task_id)
        if not task_info or task_info["status"] not in ["running", "complete"]:
            return True
        elif task_info["status"] == "complete":
            import time

            from src.config import get_config

            sync_interval_seconds = (
                get_config().get("google.sync_interval_minutes", 5) * 60
            )
            last_update_time = task_info.get("last_update_time", 0)
            current_time = time.time()
            if current_time - last_update_time > sync_interval_seconds:
                task_info["status"] = "pending_refresh"
                return True
    return False


def _start_calendar_background_sync(current_month: int, current_year: int) -> None:
    """Start calendar background sync thread."""
    from src.google_integration.routes import fetch_google_events_background

    google_thread = threading.Thread(
        target=fetch_google_events_background, args=(current_month, current_year)
    )
    google_thread.daemon = True
    google_thread.start()


def _should_start_chores_background_task() -> bool:
    """Check if chores background task should be started."""
    chores_task_id = "tasks"
    with google_fetch_lock:
        chores_task_info = background_tasks.get(chores_task_id)
        if not chores_task_info or chores_task_info["status"] not in [
            "running",
            "complete",
        ]:
            return True
    return False


def _start_chores_background_sync() -> None:
    """Start chores background sync (direct call, not threaded)."""
    chores_task_id = "tasks"
    try:
        from src.google_integration.routes import fetch_google_tasks_background

        fetch_google_tasks_background()
    except Exception as e:
        print(f"Error during automatic chores refresh: {e}")
        with google_fetch_lock:
            if chores_task_id in background_tasks:
                background_tasks[chores_task_id]["status"] = "error"


def _build_calendar_weeks_data(
    current_year: int, current_month: int, today_date: datetime.date, db_events: list
) -> list:
    """Build calendar weeks data structure for template."""
    calendar.setfirstweekday(calendar.SUNDAY)
    month_calendar = calendar.monthcalendar(current_year, current_month)
    weeks_data = []

    for week in month_calendar:
        week_data = []
        for day_num in week:
            if day_num == 0:
                week_data.append(
                    {
                        "day_number": "",
                        "is_current_month": False,
                        "events": [],
                        "is_today": False,
                    }
                )
            else:
                day_date = datetime.date(current_year, current_month, day_num)
                is_today = day_date == today_date
                day_events = _filter_events_for_day(db_events, day_date)

                week_data.append(
                    {
                        "day_number": day_num,
                        "is_current_month": True,
                        "events": day_events,
                        "is_today": is_today,
                    }
                )
        weeks_data.append(week_data)

    return weeks_data


def _get_weather_data_safe():
    """Safely get weather data with exception handling."""
    try:
        from src.weather_integration.api import get_weather_data

        return get_weather_data()
    except Exception:
        return None


def _normalize_event_timezone(
    event: dict,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Normalize event datetime objects to have timezone info."""
    start_dt = event["start_datetime"]
    end_dt = event["end_datetime"]

    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

    return start_dt, end_dt


def _is_midnight_end(dt: datetime.datetime) -> bool:
    """Check if datetime represents exactly midnight (00:00:00)."""
    return dt.hour == 0 and dt.minute == 0 and dt.second == 0


def _is_single_day_event_relevant(
    start_date: datetime.date, end_date: datetime.date, target_date: datetime.date
) -> bool:
    """Check if a single-day event is relevant for the target date."""
    return start_date == end_date and target_date == start_date


def _is_multi_day_event_relevant(
    start_date: datetime.date,
    end_date: datetime.date,
    target_date: datetime.date,
    is_midnight_end: bool,
) -> bool:
    """Check if a multi-day event is relevant for the target date."""
    if not (start_date <= target_date <= end_date):
        return False

    # Special case: don't show events that end at 00:00 on their end date
    # (unless it's a same-day event)
    if target_date == end_date and is_midnight_end and start_date != end_date:
        return False

    return True


def _is_event_relevant_for_date(event: dict, target_date: datetime.date) -> bool:
    """Check if an event is relevant for a specific target date."""
    start_dt, end_dt = _normalize_event_timezone(event)
    start_date = start_dt.date()
    end_date = end_dt.date()
    is_midnight_end = _is_midnight_end(end_dt)

    # Case 1: Single-day events
    if start_date == end_date:
        return _is_single_day_event_relevant(start_date, end_date, target_date)

    # Case 2: Multi-day events
    return _is_multi_day_event_relevant(
        start_date, end_date, target_date, is_midnight_end
    )


def _filter_events_for_day(events: list, target_date: datetime.date) -> list:
    """Filters and sorts a list of events for a specific target date."""
    day_events = [
        event for event in events if _is_event_relevant_for_date(event, target_date)
    ]

    day_events.sort(key=lambda x: (not x["all_day"], x["start_datetime"]))
    return day_events


@calendar_bp.route("/")
@calendar_bp.route("/<int:year>/<int:month>")
def view(year: int = None, month: int = None):
    """Renders the calendar view for a specific month and year."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)

    # Set defaults and validate input
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if not 1 <= month <= 12:
        return "Invalid month", 404

    current_year = year
    current_month = month
    today_date = now.date()

    # Calculate navigation dates
    prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
        current_year, current_month
    )

    # Register current month in database
    current_calendar_month = CalendarMonth(year=current_year, month=current_month)
    db.add_month(current_calendar_month)

    # Handle calendar background sync
    task_id = f"calendar.{current_month}.{current_year}"
    if _should_start_calendar_background_task(task_id):
        _start_calendar_background_sync(current_month, current_year)

    # Handle chores background sync
    if _should_start_chores_background_task():
        _start_chores_background_sync()

    # Get calendar events data
    db_events = db.get_all_events_for_month_range(current_year, current_month)
    weeks_data = _build_calendar_weeks_data(
        current_year, current_month, today_date, db_events
    )
    today_events = _filter_events_for_day(db_events, today_date)

    # Get additional data for template
    weather_data = _get_weather_data_safe()

    from src.chores_app import database as chores_db

    chores_to_display = chores_db.get_chores()

    month_name = calendar.month_name[current_month]

    from src.config import get_config

    config = get_config()

    return render_template(
        "index.html",
        weeks=weeks_data,
        today_events=today_events,
        chores=chores_to_display,
        weather=weather_data,
        month_name=month_name,
        month_number=current_month,
        year=current_year,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        today_actual_day=today_date.day,
        today_actual_month=today_date.month,
        today_actual_year=today_date.year,
        debug_enabled=config.get("app.debug", False),
        show_pir_feedback=config.get("ui.show_pir_feedback", False),
        family_name=config.get("app.family_name", "Family"),
    )


def _sync_photos_if_needed() -> None:
    """Sync photos occasionally (every 10 minutes) to avoid excessive operations."""
    import time

    from src.slideshow import database as slideshow_db

    last_photo_sync_key = "_last_photo_sync"
    current_time = time.time()

    if (
        last_photo_sync_key not in background_tasks
        or current_time - background_tasks[last_photo_sync_key].get("last_sync", 0)
        > 600
    ):  # 10 minutes
        slideshow_db.sync_photos(current_app.static_folder)
        background_tasks[last_photo_sync_key] = {"last_sync": current_time}


def _check_calendar_task_status(calendar_task_id: str) -> tuple[str, bool, bool]:
    """Check calendar task status and return status info.

    Returns:
        tuple: (task_status, events_changed, should_trigger_refresh)
    """
    import time

    from src.config import get_config

    calendar_task_info = background_tasks.get(calendar_task_id)
    if not calendar_task_info:
        return "not_tracked", False, True

    calendar_task_status = calendar_task_info["status"]
    events_changed = False
    should_trigger_refresh = False

    if calendar_task_status == "complete":
        events_changed = calendar_task_info.get("events_changed", False)
        if events_changed:
            calendar_task_info["events_changed"] = False
            calendar_task_info["updated"] = False

        # Check if we need to trigger a refresh due to time elapsed
        sync_interval_seconds = get_config().get("google.sync_interval_minutes", 5) * 60
        last_update_time = calendar_task_info.get("last_update_time", 0)
        current_time = time.time()
        if current_time - last_update_time > sync_interval_seconds:
            should_trigger_refresh = True
            calendar_task_info["status"] = "pending_refresh"

    return calendar_task_status, events_changed, should_trigger_refresh


def _check_chores_task_status(chores_task_id: str) -> tuple[str, bool]:
    """Check chores task status and return status info.

    Returns:
        tuple: (task_status, chores_changed)
    """
    chores_task_info = background_tasks.get(chores_task_id)
    if not chores_task_info:
        return "not_tracked", False

    chores_task_status = chores_task_info["status"]
    chores_changed = False

    if chores_task_status == "complete":
        chores_changed = chores_task_info.get("chores_changed", False)
        if chores_changed:
            chores_task_info["chores_changed"] = False
            chores_task_info["updated"] = False

    return chores_task_status, chores_changed


def _trigger_calendar_refresh_if_needed(
    should_trigger_refresh: bool, month: int, year: int
) -> None:
    """Trigger background calendar refresh if needed."""
    if not should_trigger_refresh:
        return

    import threading

    from src.google_integration.routes import fetch_google_events_background

    google_thread = threading.Thread(
        target=fetch_google_events_background, args=(month, year)
    )
    google_thread.daemon = True
    google_thread.start()
    print(
        f"Triggered background refresh for {month}/{year} due to time elapsed or missing task"
    )


@calendar_bp.route("/check-updates/<int:year>/<int:month>")
def check_updates(year: int, month: int):
    """API endpoint to check if the background task detected calendar or chore updates."""
    calendar_task_id = f"calendar.{month}.{year}"
    chores_task_id = "tasks"

    # Sync photos occasionally
    _sync_photos_if_needed()

    # Initialize status variables
    updates_available = False
    should_trigger_refresh = False

    with google_fetch_lock:
        # Check calendar task status
        calendar_task_status, events_changed, calendar_refresh_needed = (
            _check_calendar_task_status(calendar_task_id)
        )
        if events_changed:
            updates_available = True
        if calendar_refresh_needed:
            should_trigger_refresh = True

        # Check chores task status
        chores_task_status, chores_changed = _check_chores_task_status(chores_task_id)
        if chores_changed:
            updates_available = True

    # Trigger refresh outside of lock
    _trigger_calendar_refresh_if_needed(should_trigger_refresh, month, year)

    return jsonify(
        {
            "calendar_status": calendar_task_status,
            "chores_status": chores_task_status,
            "updates_available": updates_available,
            "events_changed": events_changed,
            "chores_changed": chores_changed,
            "refresh_triggered": should_trigger_refresh,
        }
    )
