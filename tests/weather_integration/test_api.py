"""Tests for src/weather_integration/api.py."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.weather_integration.api import (
    _deserialize_from_cache,
    _serialize_for_cache,
    load_cached_weather,
    save_weather_cache,
)


class TestSerializeForCache:
    """Tests for _serialize_for_cache."""

    def test_serializes_datetime(self):
        dt = datetime(2025, 5, 15, 10, 30, 0)
        result = _serialize_for_cache(dt)
        assert result == "2025-05-15T10:30:00"

    def test_serializes_dict(self):
        data = {"time": datetime(2025, 5, 15, 10, 0), "temp": 70}
        result = _serialize_for_cache(data)
        assert result["time"] == "2025-05-15T10:00:00"
        assert result["temp"] == 70

    def test_serializes_list(self):
        data = [datetime(2025, 5, 15), datetime(2025, 5, 16)]
        result = _serialize_for_cache(data)
        assert all(isinstance(x, str) for x in result)

    def test_passes_through_scalars(self):
        assert _serialize_for_cache(42) == 42
        assert _serialize_for_cache("hello") == "hello"
        assert _serialize_for_cache(None) is None


class TestDeserializeFromCache:
    """Tests for _deserialize_from_cache."""

    def test_deserializes_time_key(self):
        data = {"time": "2025-05-15T10:00:00"}
        result = _deserialize_from_cache(data)
        assert isinstance(result["time"], datetime)
        assert result["time"].hour == 10

    def test_deserializes_sunrise_sunset(self):
        data = {
            "sunrise": "2025-05-15T06:00:00",
            "sunset": "2025-05-15T20:00:00",
        }
        result = _deserialize_from_cache(data)
        assert isinstance(result["sunrise"], datetime)
        assert isinstance(result["sunset"], datetime)

    def test_passes_through_non_date_keys(self):
        data = {"temperature": 70, "description": "sunny"}
        result = _deserialize_from_cache(data)
        assert result["temperature"] == 70
        assert result["description"] == "sunny"

    def test_handles_nested_dicts(self):
        data = {"current": {"time": "2025-05-15T10:00:00", "temp": 70}}
        result = _deserialize_from_cache(data)
        assert isinstance(result["current"]["time"], datetime)

    def test_handles_list_of_dicts(self):
        data = [{"time": "2025-05-15T10:00:00"}, {"time": "2025-05-16T10:00:00"}]
        result = _deserialize_from_cache(data)
        assert isinstance(result[0]["time"], datetime)
        assert isinstance(result[1]["time"], datetime)

    def test_invalid_date_string_kept_as_string(self):
        data = {"time": "not-a-date"}
        result = _deserialize_from_cache(data)
        assert result["time"] == "not-a-date"


class TestWeatherCacheRoundTrip:
    """Tests for save and load weather cache."""

    def test_save_and_load(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            data = {
                "current": {"time": datetime(2025, 5, 15, 10, 0), "temp": 70},
                "daily": [],
            }
            save_weather_cache(data)
            assert cache_file.exists()

            loaded = load_cached_weather()
            assert loaded is not None
            assert loaded["current"]["temp"] == 70

    def test_load_missing_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            assert load_cached_weather() is None

    def test_load_expired_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            # Write cache with old timestamp
            cache_data = {
                "cached_at": (datetime.now() - timedelta(hours=25)).isoformat(),
                "data": {"current": {"temp": 70}, "daily": []},
            }
            cache_file.write_text(json.dumps(cache_data))

            assert load_cached_weather() is None

    def test_load_corrupted_cache_returns_none(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            cache_file.write_text("not valid json{{{")
            assert load_cached_weather() is None
