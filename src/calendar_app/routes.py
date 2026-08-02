import calendar
import datetime
import logging
import threading
from typing import Optional

from flask import Blueprint, Response, current_app, jsonify, render_template

# Shared sync state. Imported from src.sync_state rather than src.main so this
# module does not participate in an import cycle with the app factory.
from src import sync_state
from src.sync_state import registry

from . import database as db
from .models import CalendarMonth

logger = logging.getLogger(__name__)

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


def _sync_interval_seconds() -> float:
    """How long a completed sync stays fresh before a refresh is worthwhile."""
    from src.config import get_config

    return get_config().get("google.sync_interval_minutes", 5) * 60


def _should_start_calendar_background_task(task_id: str) -> bool:
    """Whether a calendar sync for this month is worth starting right now.

    Read-only. Claiming the slot belongs to the registry, which does it as
    part of dispatching the work -- a caller that marked the task itself
    could hand the worker a status the worker then refuses to take over.
    """
    return registry.is_stale(task_id, _sync_interval_seconds())


def _start_calendar_background_sync(current_month: int, current_year: int) -> None:
    """Start a calendar background sync, if one is not already in flight."""
    from src.google_integration.routes import start_calendar_sync

    start_calendar_sync(current_month, current_year)


def _should_start_chores_background_task() -> bool:
    """Check if a chores background sync is worth starting from the page render.

    Read-only on purpose: claiming the task (and every later status change) is
    owned by the sync starter/worker in src/google_integration/routes.py, so a
    caller can never latch a status the worker then refuses to take over.
    """
    from src.google_integration.routes import TASKS_TASK_ID

    # Staleness-based, matching the calendar path. Previously any "complete"
    # chores task blocked further syncs from the render path for the life of
    # the process, leaving chore freshness entirely to the browser poll.
    return registry.is_stale(TASKS_TASK_ID, _sync_interval_seconds())


def _start_chores_background_sync() -> None:
    """Queue the chores sync on the shared thread pool.

    `start_tasks_sync` claims the "tasks" slot atomically and leaves the
    status lifecycle to the worker, so the page render never waits on a
    Google Tasks round-trip.
    """
    try:
        from src.google_integration.routes import start_tasks_sync

        start_tasks_sync()
    except Exception as e:
        logger.error("Error queueing automatic chores refresh: %s", e)


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


WEATHER_TASK_ID = "weather"


def _should_start_weather_refresh() -> bool:
    """Atomically claim the weather refresh slot, if a refresh is due.

    Returns False when a refresh is already in flight or when the last
    attempt was too recent (a failing API must not be retried once per page
    render while the Pi is offline).
    """
    from src.config import get_config

    # The registry treats an in-flight task as not stale, so this covers both
    # "already queued" and "attempted too recently". finalize() stamps the
    # completion time on the error path too, so a failing fetch backs off
    # instead of retrying on every render while the Pi is offline.
    cooldown_seconds = get_config().get("weather.cache_duration", 600)
    return registry.is_stale(WEATHER_TASK_ID, cooldown_seconds)


def _refresh_weather_background() -> None:
    """Fetch weather in a worker thread and refresh the on-disk cache."""
    if not registry.mark_running(WEATHER_TASK_ID):
        return

    try:
        from src.weather_integration.api import get_weather_data

        if get_weather_data() is None:
            registry.update(WEATHER_TASK_ID, status=sync_state.ERROR)
    except Exception as e:
        logger.error("Error refreshing weather data: %s", e)
        registry.update(WEATHER_TASK_ID, status=sync_state.ERROR)
    finally:
        registry.finalize(WEATHER_TASK_ID)


def _start_weather_background_refresh() -> None:
    """Queue a weather refresh on the shared thread pool."""
    if not _should_start_weather_refresh():
        return

    try:
        registry.submit(WEATHER_TASK_ID, _refresh_weather_background)
    except Exception as e:
        logger.error("Could not queue weather refresh: %s", e)
        registry.update(WEATHER_TASK_ID, status=sync_state.ERROR)


def _get_weather_data_safe():
    """Return weather for the page render without blocking on the network.

    Reads only the on-disk cache; the live fetch happens on the shared sync
    executor. Returns None when no usable reading exists, which the template
    renders as "Weather data unavailable" - never invented values.
    """
    try:
        from src.weather_integration.api import (
            get_weather_for_display,
            weather_cache_needs_refresh,
        )

        if weather_cache_needs_refresh():
            _start_weather_background_refresh()
        return get_weather_for_display()
    except Exception as e:
        logger.error("Error preparing weather data for render: %s", e)
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


def html_fragment_response(html: str) -> Response:
    """Wrap rendered partial markup in the fragment response contract.

    One helper for every fragment endpoint so the headers cannot drift apart:
    HTML with an explicit charset, and never cached - fragments exist precisely
    because the data behind them just changed.
    """
    response = Response(html, mimetype="text/html")
    response.headers["Cache-Control"] = "no-store"
    return response


def build_calendar_context(
    current_year: int, current_month: int, today_date: datetime.date
) -> dict:
    """Assemble the template context shared by the full page and the fragments.

    The full page and the fragment endpoints must render the partials from an
    identical context: if they drift, the display visibly changes appearance
    the moment it live-updates. Sharing one builder is what guarantees they
    cannot.

    Deliberately read-only. Nothing here starts a background sync, so a
    fragment fetched on every data-change notification cannot feed back into
    starting more syncs. The sync triggers stay in `view`, which runs once per
    real page load.
    """
    prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
        current_year, current_month
    )

    db_events = db.get_all_events_for_month_range(current_year, current_month)
    weeks_data = _build_calendar_weeks_data(
        current_year, current_month, today_date, db_events
    )
    today_events = _filter_events_for_day(db_events, today_date)

    from src.chores_app.routes import build_chores_context
    from src.config import get_config

    config = get_config()

    return {
        "weeks": weeks_data,
        "today_events": today_events,
        "month_name": calendar.month_name[current_month],
        "month_number": current_month,
        "year": current_year,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "today_actual_day": today_date.day,
        "today_actual_month": today_date.month,
        "today_actual_year": today_date.year,
        "debug_enabled": config.get("app.debug", False),
        "show_pir_feedback": config.get("ui.show_pir_feedback", False),
        "family_name": config.get("app.family_name", "Family"),
        **build_chores_context(),
    }


def _local_now() -> datetime.datetime:
    """Now in the configured local timezone.

    Local time, not UTC: this drives both the default month and which cell is
    highlighted as "today". Under UTC the highlight jumped to tomorrow at
    local evening (8pm in America/New_York) on a display that is on all night.
    """
    from src.config import get_local_timezone

    return datetime.datetime.now(tz=get_local_timezone())


@calendar_bp.route("/")
@calendar_bp.route("/<int:year>/<int:month>")
def view(year: int = None, month: int = None):
    """Renders the calendar view for a specific month and year."""
    now = _local_now()

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

    # Sync triggering lives here, in the full page render, and not in the
    # shared context builder: the fragment endpoints reuse the builder and must
    # stay read-only.
    context = build_calendar_context(current_year, current_month, today_date)

    return render_template(
        "index.html",
        weather=_get_weather_data_safe(),
        **context,
    )


@calendar_bp.route("/fragment/<int:year>/<int:month>")
def fragment(year: int, month: int):
    """Render just the calendar component, for in-place client updates.

    Returns the same markup the full page carries for this month, so the client
    can swap one region instead of calling location.reload() - a full reload on
    a wall display resets the slideshow position, scroll state and any open UI.

    Read-only: no calendar, chores or weather sync is started here. The client
    fetches this on every change notification, so a sync trigger would be a
    feedback loop.
    """
    if not 1 <= month <= 12:
        return "Invalid month", 404

    context = build_calendar_context(year, month, _local_now().date())
    return html_fragment_response(
        render_template("components/calendar.html", **context)
    )


PHOTO_SYNC_INTERVAL_SECONDS = 600

# Guarded by _photo_sync_lock rather than stored in the sync registry: this is
# a plain rate-limit timestamp, not a background task with a status lifecycle,
# and keeping it out of the registry stops it showing up in task lookups.
_last_photo_sync = 0.0
_photo_sync_lock = threading.Lock()


def _sync_photos_if_needed() -> None:
    """Sync photos occasionally (every 10 minutes) to avoid excessive operations."""
    global _last_photo_sync
    import time

    from src.slideshow import database as slideshow_db

    now = time.time()
    with _photo_sync_lock:
        if now - _last_photo_sync <= PHOTO_SYNC_INTERVAL_SECONDS:
            return
        # Claim the slot before the scan so concurrent pollers do not all
        # stat the photos directory at once.
        _last_photo_sync = now

    slideshow_db.sync_photos(current_app.static_folder)


def _check_calendar_task_status(calendar_task_id: str) -> tuple[str, bool, bool]:
    """Check calendar task status and return status info.

    Returns:
        tuple: (task_status, events_changed, should_trigger_refresh)
    """
    status = registry.status(calendar_task_id)
    if status is None:
        return "not_tracked", False, True

    events_changed = False
    if status == sync_state.COMPLETE:
        events_changed = registry.consume_flag(calendar_task_id, "events_changed")

    # is_stale() reports False while a sync is in flight, so this never
    # queues a duplicate on top of one that is already running.
    should_trigger_refresh = registry.is_stale(
        calendar_task_id, _sync_interval_seconds()
    )

    return status, events_changed, should_trigger_refresh


def _check_chores_task_status(chores_task_id: str) -> tuple[str, bool]:
    """Check chores task status and return status info.

    Returns:
        tuple: (task_status, chores_changed)
    """
    status = registry.status(chores_task_id)
    if status is None:
        return "not_tracked", False

    chores_changed = False
    if status == sync_state.COMPLETE:
        chores_changed = registry.consume_flag(chores_task_id, "chores_changed")

    return status, chores_changed


def _trigger_calendar_refresh_if_needed(
    should_trigger_refresh: bool, month: int, year: int
) -> tuple[bool, Optional[str]]:
    """Queue a background calendar refresh if one is due.

    Returns ``(queued, error)`` describing what actually happened, not what was
    intended. Both parts matter to the caller:

    * ``queued`` is False when ``start_calendar_sync`` declined because another
      poller claimed the slot between the staleness read and this call. The
      staleness read is necessarily stale by the time we act on it, so it must
      not be reported to the client as if it were the outcome.
    * ``error`` is set when the work could not be queued at all. The registry
      re-raises if the pool rejects the submission, which is what a
      ThreadPoolExecutor does for the entire duration of shutdown. Letting that
      escape would be a failure of the *endpoint*, which is polled by every
      connected display every few seconds and whose exceptions are recorded by
      the catch-all handler as critical errors counting towards the health
      monitor's restart threshold. Failing to start a refresh does not stop the
      endpoint reporting the task status it just read, so it degrades instead.
    """
    if not should_trigger_refresh:
        return False, None

    from src.google_integration.routes import start_calendar_sync

    try:
        queued = start_calendar_sync(month, year)
    except Exception as e:
        logger.error(
            "Could not queue background calendar refresh for %s/%s: %s", month, year, e
        )
        return False, str(e)

    if queued:
        logger.info(
            "Triggered background refresh for %s/%s due to time elapsed or missing task",
            month,
            year,
        )
    return queued, None


@calendar_bp.route("/check-updates/<int:year>/<int:month>")
def check_updates(year: int, month: int):
    """API endpoint to check if the background task detected calendar or chore updates."""
    from src.google_integration.routes import TASKS_TASK_ID, calendar_task_id

    cal_task_id = calendar_task_id(month, year)

    # Sync photos occasionally
    _sync_photos_if_needed()

    # No lock held here: each registry call takes the lock itself, and the
    # flag reads are atomic read-and-clear. Holding one lock across all of
    # them bought nothing -- these are independent tasks -- and the old code
    # called the refresh trigger outside it anyway.
    calendar_task_status, events_changed, should_trigger_refresh = (
        _check_calendar_task_status(cal_task_id)
    )
    chores_task_status, chores_changed = _check_chores_task_status(TASKS_TASK_ID)
    updates_available = events_changed or chores_changed

    # What was reported here used to be the pre-trigger staleness read, so the
    # client could be told a refresh was coming when the trigger had in fact
    # declined (or failed). calendar.js waits 3s and re-polls on
    # refresh_triggered, so an optimistic True costs a wasted round trip and a
    # sync that never arrives.
    refresh_triggered, refresh_error = _trigger_calendar_refresh_if_needed(
        should_trigger_refresh, month, year
    )

    return jsonify(
        {
            "calendar_status": calendar_task_status,
            "chores_status": chores_task_status,
            "updates_available": updates_available,
            "events_changed": events_changed,
            "chores_changed": chores_changed,
            "refresh_triggered": refresh_triggered,
            # Null on the happy path. An extra field the frontend ignores is
            # how the failure stays visible (to /health, to a curl, to logs)
            # without the endpoint having to fail.
            "refresh_error": refresh_error,
        }
    )
