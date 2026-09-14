import calendar
import datetime
import logging
from typing import Optional

from flask import Blueprint, jsonify, request

# Shared sync state. Imported from src.sync_state rather than src.main so this
# module does not participate in an import cycle with the app factory.
from src.sync_state import registry

from . import database as db
from .models import CalendarMonth

logger = logging.getLogger(__name__)

calendar_bp = Blueprint("calendar", __name__)


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


def _local_now() -> datetime.datetime:
    """Now in the configured local timezone.

    Local time, not UTC: this drives both the default month and which cell is
    highlighted as "today". Under UTC the highlight jumped to tomorrow at
    local evening on a display that is on all night.
    """
    from src.config import get_local_timezone

    return datetime.datetime.now(tz=get_local_timezone())


def serialize_event(event: dict, tz) -> dict:
    """JSON shape of one event, with instants expressed in the display timezone."""
    start_dt, end_dt = _normalize_event_timezone(event)
    return {
        "id": event.get("google_event_id") or event.get("id"),
        "title": event.get("title") or "",
        "calendar_name": event.get("calendar_name") or "Unknown Calendar",
        "color": event.get("calendar_color") or "#808080",
        "all_day": bool(event.get("all_day")),
        "start": start_dt.astimezone(tz).isoformat(),
        "end": end_dt.astimezone(tz).isoformat(),
        "location": event.get("location") or "",
        "description": event.get("description") or "",
    }


def build_month_payload(
    year: int, month: int, today_date: datetime.date, db_events: list, tz
) -> dict:
    """Assemble the JSON the calendar grid renders from.

    Per-day event lists are computed here, with the same relevance rules the
    server has always used, so the client never re-implements the multi-day
    and midnight-end edge cases.
    """
    weeks_data = _build_calendar_weeks_data(year, month, today_date, db_events)
    weeks: list[list[Optional[dict]]] = []
    for week in weeks_data:
        row: list[Optional[dict]] = []
        for day in week:
            if not day["is_current_month"]:
                row.append(None)
                continue
            date = datetime.date(year, month, day["day_number"])
            row.append(
                {
                    "date": date.isoformat(),
                    "day": day["day_number"],
                    "is_today": day["is_today"],
                    "events": [serialize_event(e, tz) for e in day["events"]],
                }
            )
        weeks.append(row)

    prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
        year, month
    )
    return {
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "today": today_date.isoformat(),
        "weeks": weeks,
        "prev": {"year": prev_year, "month": prev_month},
        "next": {"year": next_year, "month": next_month},
    }


@calendar_bp.route("/api/calendar/<int:year>/<int:month>")
def month_api(year: int, month: int):
    """Events for a month, grouped by day, plus navigation metadata.

    Also queues a Google sync for the month when the cached copy is stale.
    That is safe against feedback loops: the sync only publishes
    ``calendar_changed`` when the data actually differs, and the registry
    deduplicates by staleness, so a client re-fetching on every change
    notification cannot cause a second sync.
    """
    if not 1 <= month <= 12 or not 1970 <= year <= 9999:
        return jsonify({"error": "Invalid month"}), 404

    from src.config import get_local_timezone

    tz = get_local_timezone()
    now = datetime.datetime.now(tz=tz)

    db.add_month(CalendarMonth(year=year, month=month))

    if request.args.get("sync", "1") != "0":
        task_id = f"calendar.{month}.{year}"
        if _should_start_calendar_background_task(task_id):
            _start_calendar_background_sync(month, year)

    db_events = db.get_all_events_for_month_range(year, month)
    payload = build_month_payload(year, month, now.date(), db_events, tz)
    payload["sync_status"] = registry.status(f"calendar.{month}.{year}")
    return jsonify(payload)


@calendar_bp.route("/api/calendar/day/<date_str>")
def day_api(date_str: str):
    """Events for a single day (used by the day panel for today)."""
    try:
        target = datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date"}), 404

    from src.config import get_local_timezone

    tz = get_local_timezone()
    db_events = db.get_all_events_for_month_range(target.year, target.month)
    return jsonify(
        {
            "date": target.isoformat(),
            "events": [
                serialize_event(e, tz)
                for e in _filter_events_for_day(db_events, target)
            ],
        }
    )
