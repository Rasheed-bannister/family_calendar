"""Weather HTTP surface and background refresh.

``GET /api/weather`` never touches the network: it serves the on-disk cache
and, if that is stale, queues a refresh on the shared sync pool. The refresh
publishes ``weather_changed`` when it lands, so the display re-fetches.
"""

from __future__ import annotations

import datetime
import logging

from flask import Blueprint, jsonify

from src import events, sync_state
from src.events import broker
from src.sync_state import registry

from .utils import get_weather_icon

logger = logging.getLogger(__name__)

weather_bp = Blueprint("weather", __name__, url_prefix="/api")

WEATHER_TASK_ID = "weather"


def _should_start_weather_refresh() -> bool:
    """Whether a refresh is due (not in flight, not attempted too recently).

    ``finalize()`` stamps the completion time on the error path too, so a
    failing fetch backs off instead of retrying on every request while the
    Pi is offline.
    """
    from src.config import get_config

    cooldown_seconds = get_config().get("weather.cache_duration", 600)
    return registry.is_stale(WEATHER_TASK_ID, cooldown_seconds)


def _refresh_weather_background() -> None:
    """Fetch weather in a worker thread and refresh the on-disk cache."""
    if not registry.mark_running(WEATHER_TASK_ID):
        return

    try:
        from .api import get_weather_data

        data = get_weather_data()
        if data is None:
            registry.update(WEATHER_TASK_ID, status=sync_state.ERROR)
        else:
            broker.publish(events.WEATHER_CHANGED)
    except Exception as e:
        logger.error("Error refreshing weather data: %s", e)
        registry.update(WEATHER_TASK_ID, status=sync_state.ERROR)
    finally:
        registry.finalize(WEATHER_TASK_ID)


def start_weather_background_refresh() -> None:
    """Queue a weather refresh on the shared thread pool, if one is due."""
    if not _should_start_weather_refresh():
        return
    try:
        registry.submit(WEATHER_TASK_ID, _refresh_weather_background)
    except Exception as e:
        logger.error("Could not queue weather refresh: %s", e)
        registry.update(WEATHER_TASK_ID, status=sync_state.ERROR)


def _iso(value) -> object:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


def serialize_weather(data: dict) -> dict:
    current = data.get("current") or {}
    daily = data.get("daily") or []
    return {
        "current": {
            "time": _iso(current.get("time")),
            "apparent_temperature": current.get("apparent_temperature"),
            "is_day": bool(current.get("is_day")),
            "weather_code": current.get("weather_code"),
            "icon": get_weather_icon(current.get("weather_code")),
        },
        "daily": [
            {
                "date": _iso(day.get("date")),
                "weather_code": day.get("weather_code"),
                "icon": get_weather_icon(day.get("weather_code")),
                "apparent_temperature_max": day.get("apparent_temperature_max"),
                "apparent_temperature_min": day.get("apparent_temperature_min"),
                "sunrise": _iso(day.get("sunrise")),
                "sunset": _iso(day.get("sunset")),
                "precipitation_probability_max": day.get(
                    "precipitation_probability_max"
                ),
            }
            for day in daily
        ],
        "stale": bool(data.get("stale")),
        "cached_at": _iso(data.get("cached_at")),
        "age_seconds": data.get("age_seconds"),
    }


@weather_bp.route("/weather")
def weather_api():
    """Best available reading from the cache; queues a refresh when stale."""
    from .api import get_weather_for_display, weather_cache_needs_refresh

    try:
        if weather_cache_needs_refresh():
            start_weather_background_refresh()
        data = get_weather_for_display()
    except Exception as e:
        logger.error("Error preparing weather data: %s", e)
        data = None

    if not data or not data.get("current") or not data.get("daily"):
        return jsonify(
            {"available": False, "sync_status": registry.status(WEATHER_TASK_ID)}
        )

    payload = serialize_weather(data)
    payload["available"] = True
    payload["sync_status"] = registry.status(WEATHER_TASK_ID)
    return jsonify(payload)
