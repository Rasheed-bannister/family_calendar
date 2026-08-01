"""Tests for src/weather_integration/api.py."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.weather_integration.api import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    _deserialize_from_cache,
    _serialize_for_cache,
    get_request_timeout,
    get_weather_data,
    get_weather_for_display,
    load_cached_weather,
    save_weather_cache,
    weather_cache_needs_refresh,
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

    def test_load_expired_cache_usable_when_max_age_disabled(self, tmp_path):
        """An explicit `max_age=None` accepts a real-but-old reading."""
        cache_file = tmp_path / "weather_cache.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            cache_data = {
                "cached_at": (datetime.now() - timedelta(hours=48)).isoformat(),
                "data": {"current": {"temp": 61}, "daily": []},
            }
            cache_file.write_text(json.dumps(cache_data))

            loaded = load_cached_weather(max_age=None)
            assert loaded is not None
            assert loaded["current"]["temp"] == 61
            assert loaded["age_seconds"] > 47 * 3600


def _write_cache(cache_file, age, payload=None):
    """Write a weather cache file aged by `age` (a timedelta)."""
    cache_data = {
        "cached_at": (datetime.now() - age).isoformat(),
        "data": payload
        or {
            "current": {"apparent_temperature": 55, "is_day": 1, "weather_code": 3},
            "daily": [],
        },
    }
    cache_file.write_text(json.dumps(cache_data))


class TestRequestTimeout:
    """The outbound fetch must always carry an explicit deadline."""

    def test_default_timeout_is_positive(self):
        with patch("src.weather_integration.api.get_config") as mock_config:
            mock_config.return_value.get.side_effect = lambda key, default=None: default
            assert get_request_timeout() == DEFAULT_REQUEST_TIMEOUT_SECONDS
            assert get_request_timeout() > 0

    def test_timeout_read_from_config(self):
        with patch("src.weather_integration.api.get_config") as mock_config:
            mock_config.return_value.get.return_value = 3
            assert get_request_timeout() == 3.0

    def test_invalid_timeout_falls_back_to_default(self):
        for bad in ("not-a-number", None, 0, -5):
            with patch("src.weather_integration.api.get_config") as mock_config:
                mock_config.return_value.get.return_value = bad
                assert get_request_timeout() == DEFAULT_REQUEST_TIMEOUT_SECONDS


@patch("src.weather_integration.api.requests_cache.CachedSession")
@patch("src.weather_integration.api.retry")
@patch("src.weather_integration.api.openmeteo_requests.Client")
class TestGetWeatherDataFailureHandling:
    """`get_weather_data` must be bounded and must never invent readings."""

    def test_weather_api_called_with_explicit_timeout(
        self, mock_client_cls, _mock_retry, _mock_session, tmp_path
    ):
        client = mock_client_cls.return_value
        client.weather_api.side_effect = RuntimeError("network down")
        cache_file = tmp_path / "weather_cache.json"

        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            get_weather_data()

        client.weather_api.assert_called_once()
        timeout = client.weather_api.call_args.kwargs["timeout"]
        assert isinstance(timeout, float)
        assert 0 < timeout <= 60

    def test_failed_fetch_without_cache_returns_none(
        self, mock_client_cls, _mock_retry, _mock_session, tmp_path
    ):
        client = mock_client_cls.return_value
        client.weather_api.side_effect = RuntimeError("network down")
        cache_file = tmp_path / "nonexistent.json"

        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            result = get_weather_data()

        # No fabricated 70F / clear-sky payload
        assert result is None

    def test_failed_fetch_falls_back_to_real_cache_marked_stale(
        self, mock_client_cls, _mock_retry, _mock_session, tmp_path
    ):
        client = mock_client_cls.return_value
        client.weather_api.side_effect = RuntimeError("network down")
        cache_file = tmp_path / "weather_cache.json"
        _write_cache(cache_file, timedelta(hours=2))

        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            result = get_weather_data()

        assert result is not None
        assert result["current"]["apparent_temperature"] == 55
        assert result["stale"] is True

    def test_failed_fetch_ignores_cache_beyond_max_age(
        self, mock_client_cls, _mock_retry, _mock_session, tmp_path
    ):
        client = mock_client_cls.return_value
        client.weather_api.side_effect = RuntimeError("network down")
        cache_file = tmp_path / "weather_cache.json"
        _write_cache(cache_file, timedelta(hours=30))

        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            result = get_weather_data()

        assert result is None


class TestDisplayPath:
    """The render path reads the cache only - never the network."""

    def test_get_weather_for_display_makes_no_network_call(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        _write_cache(cache_file, timedelta(minutes=1))

        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            with patch(
                "src.weather_integration.api.openmeteo_requests.Client", MagicMock()
            ) as mock_client_cls:
                with patch(
                    "src.weather_integration.api.requests_cache.CachedSession",
                    MagicMock(),
                ):
                    result = get_weather_for_display()

        mock_client_cls.assert_not_called()
        assert result["current"]["apparent_temperature"] == 55
        assert result["stale"] is False

    def test_get_weather_for_display_returns_none_without_cache(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            assert get_weather_for_display() is None

    def test_display_marks_old_reading_stale(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        _write_cache(cache_file, timedelta(hours=6))

        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            result = get_weather_for_display()

        assert result["stale"] is True

    def test_cache_needs_refresh_when_missing(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            assert weather_cache_needs_refresh() is True

    def test_cache_needs_refresh_when_older_than_cache_duration(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        _write_cache(cache_file, timedelta(hours=3))
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            assert weather_cache_needs_refresh() is True

    def test_fresh_cache_does_not_need_refresh(self, tmp_path):
        cache_file = tmp_path / "weather_cache.json"
        _write_cache(cache_file, timedelta(seconds=5))
        with patch("src.weather_integration.api.WEATHER_CACHE_FILE", cache_file):
            assert weather_cache_needs_refresh() is False
