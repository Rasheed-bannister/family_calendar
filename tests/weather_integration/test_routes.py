"""Tests for src/weather_integration/routes.py: refresh gating and the JSON API."""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src import sync_state
from src.events import broker
from src.main import create_app
from src.sync_state import registry
from src.weather_integration.routes import (
    WEATHER_TASK_ID,
    _refresh_weather_background,
    _should_start_weather_refresh,
    serialize_weather,
    start_weather_background_refresh,
)


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def subscription():
    queue = broker.subscribe()
    yield queue
    broker.unsubscribe(queue)


def _types(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait()["type"])
    return out


SAMPLE = {
    "current": {
        "time": datetime(2025, 5, 15, 10, 0),
        "apparent_temperature": 70.4,
        "is_day": 1,
        "weather_code": 3,
    },
    "daily": [
        {
            "date": datetime(2025, 5, 15),
            "weather_code": 61,
            "apparent_temperature_max": 75.0,
            "apparent_temperature_min": 60.0,
            "sunrise": datetime(2025, 5, 15, 6, 0),
            "sunset": datetime(2025, 5, 15, 20, 0),
            "precipitation_probability_max": 40.0,
        }
    ],
    "stale": False,
    "cached_at": datetime(2025, 5, 15, 10, 5),
    "age_seconds": 12.0,
}


class TestWeatherRefreshGate:
    def test_starts_refresh_when_no_task_tracked(self):
        with patch.object(registry, "tasks", {}):
            assert _should_start_weather_refresh() is True
            assert registry.status(WEATHER_TASK_ID) is None

    def test_does_not_start_when_already_in_flight(self):
        for status in sync_state.IN_FLIGHT:
            tasks = {WEATHER_TASK_ID: {"status": status, "last_update_time": 0}}
            with patch.object(registry, "tasks", tasks):
                assert _should_start_weather_refresh() is False

    def test_does_not_retry_within_cooldown(self):
        tasks = {
            WEATHER_TASK_ID: {
                "status": sync_state.ERROR,
                "last_update_time": time.time(),
            }
        }
        with patch.object(registry, "tasks", tasks):
            assert _should_start_weather_refresh() is False

    def test_retries_after_cooldown_elapsed(self):
        tasks = {WEATHER_TASK_ID: {"status": sync_state.ERROR, "last_update_time": 0}}
        with patch.object(registry, "tasks", tasks):
            assert _should_start_weather_refresh() is True


class TestWeatherBackgroundRefresh:
    def test_refresh_is_submitted_to_executor(self):
        executor = MagicMock()
        with patch.object(registry, "tasks", {}):
            with patch.object(registry, "executor", executor):
                start_weather_background_refresh()
        executor.submit.assert_called_once_with(_refresh_weather_background)

    def test_not_submitted_when_not_due(self):
        executor = MagicMock()
        tasks = {WEATHER_TASK_ID: {"status": sync_state.RUNNING, "last_update_time": 0}}
        with patch.object(registry, "tasks", tasks):
            with patch.object(registry, "executor", executor):
                start_weather_background_refresh()
        executor.submit.assert_not_called()

    def test_executor_failure_is_swallowed_and_recorded(self):
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("pool is shut down")
        with patch.object(registry, "tasks", {}):
            with patch.object(registry, "executor", executor):
                start_weather_background_refresh()
                assert registry.status(WEATHER_TASK_ID) == sync_state.ERROR

    def test_worker_marks_complete_and_publishes_on_success(self, subscription):
        with patch.object(registry, "tasks", {}):
            with patch(
                "src.weather_integration.api.get_weather_data",
                return_value={"current": {}, "daily": []},
            ):
                _refresh_weather_background()
            assert registry.status(WEATHER_TASK_ID) == sync_state.COMPLETE
        assert _types(subscription) == ["weather_changed"]

    def test_worker_marks_error_when_no_data_available(self, subscription):
        with patch.object(registry, "tasks", {}):
            with patch(
                "src.weather_integration.api.get_weather_data", return_value=None
            ):
                _refresh_weather_background()
            assert registry.status(WEATHER_TASK_ID) == sync_state.ERROR
        assert _types(subscription) == []

    def test_worker_marks_error_when_fetch_raises(self):
        with patch.object(registry, "tasks", {}):
            with patch(
                "src.weather_integration.api.get_weather_data",
                side_effect=RuntimeError("network down"),
            ):
                _refresh_weather_background()
            assert registry.status(WEATHER_TASK_ID) == sync_state.ERROR


class TestSerializeWeather:
    def test_shape_and_icons(self):
        data = serialize_weather(SAMPLE)
        assert data["current"] == {
            "time": "2025-05-15T10:00:00",
            "apparent_temperature": 70.4,
            "is_day": True,
            "weather_code": 3,
            "icon": "☁️",
        }
        day = data["daily"][0]
        assert day["date"] == "2025-05-15T00:00:00"
        assert day["icon"] == "🌧️"
        assert day["sunrise"] == "2025-05-15T06:00:00"
        assert day["precipitation_probability_max"] == 40.0
        assert data["stale"] is False
        assert data["cached_at"] == "2025-05-15T10:05:00"
        assert data["age_seconds"] == 12.0

    def test_tolerates_missing_fields(self):
        data = serialize_weather({"current": {}, "daily": [{}]})
        assert data["current"]["icon"] == "❓"
        assert data["daily"][0]["sunrise"] is None
        assert data["stale"] is False


class TestWeatherApi:
    def test_serves_cached_reading_without_fetching(self, client):
        with patch.object(registry, "tasks", {}):
            with patch(
                "src.weather_integration.api.weather_cache_needs_refresh",
                return_value=False,
            ):
                with patch(
                    "src.weather_integration.api.get_weather_for_display",
                    return_value=dict(SAMPLE),
                ):
                    with patch("src.weather_integration.api.get_weather_data") as fetch:
                        response = client.get("/api/weather")
        assert response.status_code == 200
        data = response.get_json()
        assert data["available"] is True
        assert data["current"]["apparent_temperature"] == 70.4
        assert data["sync_status"] is None
        fetch.assert_not_called()

    def test_stale_cache_queues_refresh_and_still_answers(self, client):
        executor = MagicMock()
        stale = dict(SAMPLE, stale=True)
        with patch.object(registry, "tasks", {}):
            with patch.object(registry, "executor", executor):
                with patch(
                    "src.weather_integration.api.weather_cache_needs_refresh",
                    return_value=True,
                ):
                    with patch(
                        "src.weather_integration.api.get_weather_for_display",
                        return_value=stale,
                    ):
                        data = client.get("/api/weather").get_json()
        executor.submit.assert_called_once_with(_refresh_weather_background)
        assert data["available"] is True
        assert data["stale"] is True
        assert data["sync_status"] == sync_state.PENDING

    def test_no_reading_is_honest(self, client):
        executor = MagicMock()
        with patch.object(registry, "tasks", {}):
            with patch.object(registry, "executor", executor):
                with patch(
                    "src.weather_integration.api.weather_cache_needs_refresh",
                    return_value=True,
                ):
                    with patch(
                        "src.weather_integration.api.get_weather_for_display",
                        return_value=None,
                    ):
                        response = client.get("/api/weather")
        assert response.status_code == 200
        assert response.get_json()["available"] is False

    def test_unexpected_error_degrades_to_unavailable(self, client):
        with patch(
            "src.weather_integration.api.weather_cache_needs_refresh",
            side_effect=RuntimeError("boom"),
        ):
            response = client.get("/api/weather")
        assert response.status_code == 200
        assert response.get_json()["available"] is False

    def test_html_fragment_endpoint_is_gone(self, client):
        assert client.get("/api/weather-update").status_code == 404
