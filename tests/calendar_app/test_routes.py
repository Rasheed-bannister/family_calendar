import datetime
import time
from unittest.mock import MagicMock, patch

import pytest

from src import sync_state

# Import the functions/blueprint to test
from src.calendar_app import routes as calendar_routes
from src.google_integration.routes import TASKS_TASK_ID

# Import the app factory function
from src.main import create_app

# Background sync state lives in the registry; it is the single seam the tests
# patch, so production code and assertions can never read different dicts.
from src.sync_state import registry

CALENDAR_TASK_ID = "calendar.5.2025"


@pytest.fixture
def client():
    """Create a Flask test client."""
    app = create_app()  # Create the app instance
    app.config["TESTING"] = True
    # If you have specific configurations for testing (e.g., database), set them here
    # app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.test_client() as client:
        with app.app_context():  # Push an application context using the created app
            # You might need to initialize extensions or databases here if needed
            # e.g., db.create_all()
            pass
        yield client
        # Clean up after tests if necessary
        # e.g., db.drop_all()


@pytest.fixture
def tasks_state():
    """Isolate the registry's task state for a single test.

    Swapping the attribute (rather than mutating the shared dict) means the
    registry's own methods read the isolated copy, and the real state is
    restored automatically even if the test fails.
    """
    with patch.object(registry, "tasks", {}) as tasks:
        yield tasks


@pytest.fixture
def mock_executor():
    """Replace the shared thread pool so no sync actually runs."""
    executor = MagicMock()
    with patch.object(registry, "executor", executor):
        yield executor


@pytest.fixture
def photo_sync_due():
    """Reset the photo-sync rate limiter so /check-updates performs a scan.

    The timestamp is a plain module global (it is a rate limit, not a task with
    a status lifecycle, so it deliberately does not live in the registry), which
    means one test's poll would otherwise suppress the next test's for the
    10-minute interval.
    """
    with patch.object(calendar_routes, "_last_photo_sync", 0.0):
        yield


# --- Tests for _filter_events_for_day ---


def test_filter_events_for_day_single_day_event():
    """Test filtering for an event that starts and ends on the target day."""
    target_date = datetime.date(2025, 5, 15)
    event = {
        "id": "1",
        "summary": "Test Event",
        "start_datetime": datetime.datetime(
            2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 15, 11, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": False,
    }
    events = [event]
    filtered = calendar_routes._filter_events_for_day(events, target_date)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "1"


def test_filter_events_for_day_multi_day_event_spanning():
    """Test filtering for an event that spans across the target day."""
    target_date = datetime.date(2025, 5, 15)
    event = {
        "id": "2",
        "summary": "Multi-day Event",
        "start_datetime": datetime.datetime(
            2025, 5, 14, 10, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 16, 11, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": False,
    }
    events = [event]
    filtered = calendar_routes._filter_events_for_day(events, target_date)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "2"


def test_filter_events_for_day_all_day_event():
    """Test filtering for an all-day event on the target day."""
    target_date = datetime.date(2025, 5, 15)
    event = {
        "id": "3",
        "summary": "All Day Event",
        # All-day events often represented like this by Google API (start date, end date is next day)
        "start_datetime": datetime.datetime(
            2025, 5, 15, 0, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 16, 0, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": True,
    }
    events = [event]
    filtered = calendar_routes._filter_events_for_day(events, target_date)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "3"


def test_filter_events_for_day_event_outside_target():
    """Test filtering excludes events not on the target day."""
    target_date = datetime.date(2025, 5, 15)
    event = {
        "id": "4",
        "summary": "Wrong Day Event",
        "start_datetime": datetime.datetime(
            2025, 5, 16, 10, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 16, 11, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": False,
    }
    events = [event]
    filtered = calendar_routes._filter_events_for_day(events, target_date)
    assert len(filtered) == 0


def test_filter_events_for_day_sorting():
    """Test sorting of events (all-day first, then by time)."""
    target_date = datetime.date(2025, 5, 15)
    event1 = {  # Later event
        "id": "1",
        "summary": "Later Event",
        "start_datetime": datetime.datetime(
            2025, 5, 15, 14, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 15, 15, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": False,
    }
    event2 = {  # All day event
        "id": "2",
        "summary": "All Day Event",
        "start_datetime": datetime.datetime(
            2025, 5, 15, 0, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 16, 0, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": True,
    }
    event3 = {  # Earlier event
        "id": "3",
        "summary": "Earlier Event",
        "start_datetime": datetime.datetime(
            2025, 5, 15, 9, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "end_datetime": datetime.datetime(
            2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
        ),
        "all_day": False,
    }
    events = [event1, event2, event3]
    filtered = calendar_routes._filter_events_for_day(events, target_date)
    assert len(filtered) == 3
    assert filtered[0]["id"] == "2"  # All day first
    assert filtered[1]["id"] == "3"  # Then earlier timed event
    assert filtered[2]["id"] == "1"  # Then later timed event


def test_filter_events_naive_datetime():
    """Test filtering handles naive datetimes by assuming UTC."""
    target_date = datetime.date(2025, 5, 15)
    event = {
        "id": "5",
        "summary": "Naive Event",
        "start_datetime": datetime.datetime(2025, 5, 15, 10, 0, 0),  # No tzinfo
        "end_datetime": datetime.datetime(2025, 5, 15, 11, 0, 0),  # No tzinfo
        "all_day": False,
    }
    events = [event]
    filtered = calendar_routes._filter_events_for_day(events, target_date)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "5"


# --- Tests for view route ---


@patch("src.calendar_app.routes.db")
@patch("src.weather_integration.api.weather_cache_needs_refresh", return_value=False)
@patch("src.weather_integration.api.get_weather_for_display")
def test_view_route_default(
    mock_get_weather,
    mock_needs_refresh,
    mock_db,
    client,
    tasks_state,
    mock_executor,
):
    """Test the default calendar view route (current month/year)."""
    mock_db.get_all_events.return_value = []
    # Provide a more realistic weather mock, even if not asserted directly here
    mock_get_weather.return_value = {
        "current": {
            "is_day": 1,
            "weather_code": 3,  # Example code
            "apparent_temperature": 70,
        },
        "daily": [
            {
                "date": datetime.date(2025, 5, 2),
                "sunrise": datetime.datetime(
                    2025, 5, 2, 6, 0, tzinfo=datetime.timezone.utc
                ),
                "sunset": datetime.datetime(
                    2025, 5, 2, 20, 0, tzinfo=datetime.timezone.utc
                ),
                "apparent_temperature_max": 75,
                "apparent_temperature_min": 65,
                "weather_code": 3,
                "precipitation_probability_max": 10,
            }
            # Add more days if needed for other assertions
        ],
    }

    # Mock datetime.now() to control the date
    with patch("src.calendar_app.routes.datetime") as mock_dt:
        now_fixed = datetime.datetime(
            2025, 5, 2, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_dt.datetime.now.return_value = now_fixed
        mock_dt.date.today.return_value = now_fixed.date()
        # Ensure date objects are created correctly within the mocked context
        mock_dt.date = datetime.date

        response = client.get("/calendar/")

    assert response.status_code == 200
    assert b"May 2025" in response.data  # Check month/year in output
    # Check for something rendered from the weather mock, e.g., current temp
    assert b"70\xc2\xb0" in response.data  # Check for 70° (UTF-8 encoded degree symbol)
    mock_db.add_month.assert_called_once()
    # Both syncs are queued on the thread pool: nothing runs inline in the
    # request handler (calendar events + Google Tasks/chores).
    assert mock_executor.submit.call_count == 2
    calendar_call = mock_executor.submit.call_args_list[0][0]
    assert calendar_call[1:] == (5, 2025)  # Check args passed to background task
    chores_call = mock_executor.submit.call_args_list[1][0]
    assert chores_call[0].__name__ == "fetch_google_tasks_background"


@patch("src.calendar_app.routes.db")
@patch("src.weather_integration.api.weather_cache_needs_refresh", return_value=False)
@patch("src.weather_integration.api.get_weather_for_display")
def test_view_route_specific_month(
    mock_get_weather,
    mock_needs_refresh,
    mock_db,
    client,
    tasks_state,
    mock_executor,
):
    """Test the calendar view route for a specific month/year."""
    mock_db.get_all_events.return_value = []
    # Update mock weather data to match template structure
    mock_get_weather.return_value = {
        "current": {
            "is_day": 1,
            "weather_code": 61,  # Example: Slight Rain
            "apparent_temperature": 65,
        },
        "daily": [
            {
                "date": datetime.date(
                    2025, 5, 2
                ),  # Today's date for consistency in template
                "sunrise": datetime.datetime(
                    2025, 5, 2, 6, 0, tzinfo=datetime.timezone.utc
                ),
                "sunset": datetime.datetime(
                    2025, 5, 2, 20, 0, tzinfo=datetime.timezone.utc
                ),
                "apparent_temperature_max": 68,
                "apparent_temperature_min": 60,
                "weather_code": 61,
                "precipitation_probability_max": 40,
            },
            {
                "date": datetime.date(2025, 5, 3),
                "sunrise": datetime.datetime(
                    2025, 5, 3, 6, 1, tzinfo=datetime.timezone.utc
                ),
                "sunset": datetime.datetime(
                    2025, 5, 3, 20, 1, tzinfo=datetime.timezone.utc
                ),
                "apparent_temperature_max": 70,
                "apparent_temperature_min": 58,
                "weather_code": 3,  # Partly Cloudy
                "precipitation_probability_max": 15,
            },
            # Add more forecast days if needed
        ],
    }

    # Mock datetime.now() - needed for today's date highlighting
    with patch("src.calendar_app.routes.datetime") as mock_dt:
        now_fixed = datetime.datetime(
            2025, 5, 2, 12, 0, 0, tzinfo=datetime.timezone.utc
        )
        mock_dt.datetime.now.return_value = now_fixed
        mock_dt.date.today.return_value = now_fixed.date()
        mock_dt.date = datetime.date  # Ensure date objects are created correctly

        response = client.get("/calendar/2024/11")  # Request Nov 2024

    assert response.status_code == 200
    assert b"November 2024" in response.data
    # Assert based on data actually rendered by the template
    # e.g., check for the mocked current temperature
    assert b"65\xc2\xb0" in response.data  # Check for 65°
    mock_db.add_month.assert_called_once()
    # Calendar sync for Nov 2024 plus the chores sync, both queued on the pool
    assert mock_executor.submit.call_count == 2
    calendar_call = mock_executor.submit.call_args_list[0][0]
    assert calendar_call[1:] == (11, 2024)
    chores_call = mock_executor.submit.call_args_list[1][0]
    assert chores_call[0].__name__ == "fetch_google_tasks_background"


@patch("src.calendar_app.routes.db")
@patch("src.weather_integration.api.get_weather_data")
@patch("src.weather_integration.api.weather_cache_needs_refresh", return_value=True)
@patch("src.weather_integration.api.get_weather_for_display", return_value=None)
def test_view_renders_when_weather_unavailable(
    mock_display,
    mock_needs_refresh,
    mock_live_fetch,
    mock_db,
    client,
    tasks_state,
    mock_executor,
):
    """The page still renders - and says so honestly - with no weather data."""
    mock_db.get_all_events.return_value = []

    response = client.get("/calendar/2024/11")

    assert response.status_code == 200
    assert b"Weather data unavailable" in response.data
    # No invented temperature is rendered
    assert b"70\xc2\xb0" not in response.data
    # The live fetch never runs inside the request handler
    mock_live_fetch.assert_not_called()


@patch("src.calendar_app.routes.db")
@patch("src.weather_integration.api.get_weather_data")
@patch("src.weather_integration.api.weather_cache_needs_refresh", return_value=True)
@patch("src.weather_integration.api.get_weather_for_display", return_value=None)
def test_view_queues_weather_refresh_instead_of_blocking(
    mock_display,
    mock_needs_refresh,
    mock_live_fetch,
    mock_db,
    client,
    tasks_state,
    mock_executor,
):
    """A stale/missing cache queues the fetch on the pool, never inline."""
    mock_db.get_all_events.return_value = []

    response = client.get("/calendar/2024/11")

    assert response.status_code == 200
    mock_live_fetch.assert_not_called()
    submitted = [call[0][0] for call in mock_executor.submit.call_args_list]
    assert calendar_routes._refresh_weather_background in submitted


@patch("src.calendar_app.routes.db")
@patch("src.weather_integration.api.weather_cache_needs_refresh", return_value=False)
@patch("src.weather_integration.api.get_weather_for_display", return_value=None)
@patch("src.google_integration.routes.fetch_google_tasks_background")
def test_view_dispatches_chores_sync_via_executor(
    mock_fetch_tasks,
    mock_display,
    mock_needs_refresh,
    mock_db,
    client,
    tasks_state,
    mock_executor,
):
    """The Google Tasks round-trip is queued on the pool, not run inline."""
    mock_db.get_all_events.return_value = []

    response = client.get("/calendar/2024/11")

    assert response.status_code == 200
    mock_fetch_tasks.assert_not_called()  # never executed in the request thread
    submitted = [call[0][0] for call in mock_executor.submit.call_args_list]
    assert mock_fetch_tasks in submitted
    # The registry claimed the slot on the way to the pool; the worker owns
    # every status transition from here.
    assert registry.status(TASKS_TASK_ID) == sync_state.PENDING


def test_view_route_invalid_month(client):
    """Test the calendar view route with an invalid month."""
    response = client.get("/calendar/2024/13")
    assert response.status_code == 404
    assert b"Invalid month" in response.data


# --- Tests for check_updates route ---


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
def test_check_updates_no_task(
    mock_sync_photos, client, tasks_state, mock_executor, photo_sync_due
):  # Updated mock name
    """Test check_updates when the background task is not tracked."""
    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["calendar_status"] == "not_tracked"
    assert not json_data["updates_available"]
    # An untracked month has never synced, so the poll kicks one off
    assert json_data["refresh_triggered"]
    mock_executor.submit.assert_called_once()
    mock_sync_photos.assert_called_once()  # Check slideshow sync is called using updated mock name


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
def test_check_updates_task_running(
    mock_sync_photos, client, tasks_state, mock_executor, photo_sync_due
):  # Updated mock name
    """Test check_updates when the background task is running."""
    registry.update(CALENDAR_TASK_ID, status=sync_state.RUNNING, updated=False)

    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["calendar_status"] == "running"
    assert not json_data["updates_available"]
    # A sync already in flight is never stale, so the poll must not pile a
    # duplicate on top of it
    assert not json_data["refresh_triggered"]
    mock_executor.submit.assert_not_called()
    mock_sync_photos.assert_called_once()  # Use updated mock name


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
def test_check_updates_task_complete_with_updates(
    mock_sync_photos, client, tasks_state, mock_executor, photo_sync_due
):  # Updated mock name
    """Test check_updates when the task is complete and updates are available."""
    now = time.time()
    registry.update(
        CALENDAR_TASK_ID,
        status=sync_state.COMPLETE,
        updated=True,
        events_changed=True,
        last_update_time=now,
    )
    registry.update(
        TASKS_TASK_ID,
        status=sync_state.COMPLETE,
        updated=False,
        chores_changed=False,
        last_update_time=now,
    )

    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["calendar_status"] == "complete"
    assert json_data["updates_available"]
    assert json_data["events_changed"]
    assert not json_data["chores_changed"]

    # Verify flags were reset after reading, so the change is reported exactly
    # once and the browser does not reload on every poll
    calendar_entry = registry.snapshot(CALENDAR_TASK_ID)
    assert not calendar_entry["updated"]
    assert not calendar_entry["events_changed"]
    assert not registry.snapshot(TASKS_TASK_ID)["chores_changed"]
    mock_sync_photos.assert_called_once()


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
def test_check_updates_task_complete_no_updates(
    mock_sync_photos, client, tasks_state, mock_executor, photo_sync_due
):  # Updated mock name
    """Test check_updates when the task is complete but no updates were found."""
    now = time.time()
    registry.update(
        CALENDAR_TASK_ID,
        status=sync_state.COMPLETE,
        updated=False,
        events_changed=False,
        last_update_time=now,
    )
    registry.update(
        TASKS_TASK_ID,
        status=sync_state.COMPLETE,
        updated=False,
        chores_changed=False,
        last_update_time=now,
    )

    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["calendar_status"] == "complete"
    assert not json_data["updates_available"]
    assert not json_data["events_changed"]
    assert not json_data["chores_changed"]
    mock_sync_photos.assert_called_once()
