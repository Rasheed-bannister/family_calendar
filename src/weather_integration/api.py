import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

# Import configuration
from src.config import get_config

# Cache file for offline mode
WEATHER_CACHE_FILE = Path(__file__).parent / "weather_cache.json"

# Oldest cached reading still worth showing. A real reading from a few hours
# ago beats a blank panel on a display that may be offline for a while, but
# past this point it is noise and we show nothing instead.
CACHE_MAX_AGE = timedelta(hours=24)

# Per-request network timeout (seconds). The render path never waits on the
# network any more, but an unbounded request would still pin a pool worker
# forever when the Pi loses wifi, so every request gets an explicit deadline.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0


def _discard_corrupted_cache() -> None:
    """Delete an unreadable cache file so the next fetch can rewrite it."""
    try:
        WEATHER_CACHE_FILE.unlink()
        logging.info("Removed corrupted weather cache file")
    except OSError:
        pass


def _read_cache_entry() -> Optional[tuple]:
    """Read the raw cache file, returning ``(data, cached_at)`` or None."""
    if not WEATHER_CACHE_FILE.exists():
        return None
    try:
        with open(WEATHER_CACHE_FILE, "r") as f:
            cache_data = json.load(f)
        cache_time = datetime.fromisoformat(cache_data.get("cached_at", ""))
        return _deserialize_from_cache(cache_data["data"]), cache_time
    except (ValueError, KeyError) as e:
        logging.error(f"Error loading weather cache: {e}")
        _discard_corrupted_cache()
    except Exception as e:
        logging.error(f"Unexpected error loading weather cache: {e}")
        _discard_corrupted_cache()
    return None


def load_cached_weather(
    max_age: Optional[timedelta] = CACHE_MAX_AGE,
) -> Optional[Dict[str, Any]]:
    """Load cached weather data for offline mode.

    Args:
        max_age: Reject a cache older than this. ``None`` accepts any age.

    Returns:
        The cached reading annotated with ``cached_at`` / ``age_seconds``, or
        None when there is no usable cache. Never fabricates values.
    """
    entry = _read_cache_entry()
    if entry is None:
        return None

    data, cached_at = entry
    age = datetime.now() - cached_at
    if max_age is not None and age >= max_age:
        logging.info("Weather cache is older than %s; ignoring it", max_age)
        return None

    logging.info("Using cached weather data for offline mode")
    data["cached_at"] = cached_at
    data["age_seconds"] = max(age.total_seconds(), 0.0)
    return data


def get_request_timeout() -> float:
    """Return the configured per-request network timeout in seconds."""
    timeout = get_config().get(
        "weather.request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS
    )
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        return DEFAULT_REQUEST_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_REQUEST_TIMEOUT_SECONDS


def get_weather_for_display() -> Optional[Dict[str, Any]]:
    """Return the best available reading *without* touching the network.

    Used by the page render: it must never block on an outbound HTTP call.
    Returns None when no usable cache exists so the template can honestly
    say "Weather data unavailable" instead of showing invented numbers.
    """
    data = load_cached_weather()
    if data is None:
        return None

    cache_duration = get_config().get("weather.cache_duration", 600)
    data["stale"] = data.get("age_seconds", 0) > cache_duration
    return data


def weather_cache_age_seconds() -> Optional[float]:
    """Age of the on-disk cache in seconds, or None if there is no cache."""
    entry = _read_cache_entry()
    if entry is None:
        return None
    return max((datetime.now() - entry[1]).total_seconds(), 0.0)


def weather_cache_needs_refresh() -> bool:
    """True when the cache is missing or older than ``weather.cache_duration``."""
    age = weather_cache_age_seconds()
    if age is None:
        return True
    return age > get_config().get("weather.cache_duration", 600)


def _serialize_for_cache(obj):
    """Convert datetime objects and other non-JSON-serializable objects to strings."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, (pd.Timestamp, pd.DatetimeIndex)):
        return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
    elif isinstance(obj, dict):
        return {key: _serialize_for_cache(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_cache(item) for item in obj]
    elif hasattr(obj, "item"):  # numpy types
        return obj.item()
    elif hasattr(obj, "tolist"):  # numpy arrays
        return obj.tolist()
    else:
        return obj


def _deserialize_from_cache(obj):
    """Convert ISO strings back to datetime objects where appropriate."""
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in ["time", "sunrise", "sunset", "date"] and isinstance(value, str):
                try:
                    result[key] = datetime.fromisoformat(value)
                except ValueError:
                    result[key] = value
            else:
                result[key] = _deserialize_from_cache(value)
        return result
    elif isinstance(obj, list):
        return [_deserialize_from_cache(item) for item in obj]
    else:
        return obj


def save_weather_cache(data: Dict[str, Any]):
    """Save weather data to cache for offline use."""
    try:
        # Serialize datetime objects before caching
        serializable_data = _serialize_for_cache(data)

        cache_data = {
            "cached_at": datetime.now().isoformat(),
            "data": serializable_data,
        }
        with open(WEATHER_CACHE_FILE, "w") as f:
            json.dump(cache_data, f, indent=2)
    except (IOError, ValueError) as e:
        logging.error(f"Error saving weather cache: {e}")


def get_weather_data() -> Optional[Dict[str, Any]]:
    """Fetch current weather and daily forecast from Open-Meteo.

    Performs network I/O, so it must be called from a background worker and
    never from a request handler. Every request carries an explicit timeout
    (see ``get_request_timeout``) so a hung or unreachable API cannot pin a
    worker indefinitely.

    Returns:
        The weather payload, a real (possibly stale) cached reading when the
        fetch fails and offline fallback is enabled, or None. It never
        returns fabricated temperatures - callers/templates must treat None
        as "weather unavailable".
    """
    config = get_config()

    # Get location settings from configuration
    latitude = config.get("weather.latitude", 40.759010)
    longitude = config.get("weather.longitude", -73.984474)
    timezone = config.get("weather.timezone", "America/New_York")
    cache_duration = config.get("weather.cache_duration", 300)
    offline_fallback = config.get("weather.offline_fallback", True)
    max_retry_attempts = config.get("google.max_retry_attempts", 3)

    try:
        # Setup the Open-Meteo API client with cache and retry on error
        cache_session = requests_cache.CachedSession(
            ".cache", expire_after=cache_duration
        )
        retry_session = retry(
            cache_session, retries=max_retry_attempts, backoff_factor=0.2
        )
        openmeteo = openmeteo_requests.Client(session=retry_session)

        # Make sure all required weather variables are listed here
        # The order of variables in hourly or daily is important to assign them correctly below
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": [
                "weather_code",
                "apparent_temperature_max",
                "apparent_temperature_min",
                "sunrise",
                "sunset",
                "precipitation_probability_max",
            ],
            "models": "best_match",
            "current": ["apparent_temperature", "is_day", "weather_code"],
            "timezone": timezone,
            "wind_speed_unit": "mph",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
        }
        # An explicit timeout is required: retry_requests.retry() only adds a
        # default timeout when it builds its own session, and here it is handed
        # the CachedSession, so without this the request could hang forever.
        responses = openmeteo.weather_api(
            url, params=params, timeout=get_request_timeout()
        )

        # Process first location. Add a for-loop for multiple locations or weather models
        response = responses[0]

        # Current values. The order of variables needs to be the same as requested.
        current = response.Current()
        current_data = {
            "time": datetime.fromtimestamp(
                current.Time()
            ),  # Convert timestamp to datetime
            "apparent_temperature": current.Variables(0).Value(),
            "is_day": current.Variables(1).Value(),
            "weather_code": current.Variables(2).Value(),
        }

        # Process daily data. The order of variables needs to be the same as requested.
        daily = response.Daily()
        daily_data = {
            "date": pd.date_range(
                start=pd.to_datetime(daily.Time(), unit="s", utc=True),
                end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=daily.Interval()),
                inclusive="left",
            )
        }
        daily_data["weather_code"] = daily.Variables(0).ValuesAsNumpy()
        daily_data["apparent_temperature_max"] = daily.Variables(1).ValuesAsNumpy()
        daily_data["apparent_temperature_min"] = daily.Variables(2).ValuesAsNumpy()
        # Convert sunrise/sunset timestamps to datetime objects
        daily_data["sunrise"] = [
            datetime.fromtimestamp(ts) for ts in daily.Variables(3).ValuesInt64AsNumpy()
        ]
        daily_data["sunset"] = [
            datetime.fromtimestamp(ts) for ts in daily.Variables(4).ValuesInt64AsNumpy()
        ]
        daily_data["precipitation_probability_max"] = daily.Variables(5).ValuesAsNumpy()

        daily_dataframe = pd.DataFrame(data=daily_data)

        # Prepare return data
        weather_data = {
            "current": current_data,
            "daily": daily_dataframe.to_dict(
                orient="records"
            ),  # Convert dataframe to list of dicts
        }

        # Save to cache for offline use
        save_weather_cache(weather_data)

        return weather_data

    except Exception as e:
        logging.error(f"Error fetching weather data: {e}")

        # Try to use cached data if offline fallback is enabled. A stale but
        # real reading is honest; it is flagged so callers can label it.
        if offline_fallback:
            cached_data = load_cached_weather()
            if cached_data:
                cached_data["stale"] = True
                return cached_data

        # No usable data. Returning None (rather than an invented 70F/clear
        # reading) lets the template show "Weather data unavailable".
        logging.warning("No weather data available: API failed and no usable cache")
        return None
