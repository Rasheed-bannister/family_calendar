import datetime
from unittest.mock import patch

import pytest

# Import the functions/blueprint to test
from src.calendar_app import routes as calendar_routes

# Import the app factory function
from src.main import create_app


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
@patch("src.weather_integration.api.get_weather_data")  # Corrected patch target
@patch("src.calendar_app.routes.threading.Thread")
@patch("src.calendar_app.routes.google_fetch_lock")
@patch("src.calendar_app.routes.background_tasks", new_callable=dict)
@patch("src.calendar_app.routes.last_known_chores", new_callable=list)
def test_view_route_default(
    mock_chores_list,
    mock_tasks,
    mock_lock,
    mock_thread,
    mock_get_weather,
    mock_db,
    client,  # Renamed mock_chores for clarity
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
    # Update mock chores to match expected structure
    mock_chores_data = [
        {"title": "Household", "notes": "Take out trash", "status": "pending"}
    ]
    mock_chores_list.extend(mock_chores_data)

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
    # Check for the actual chore text rendered by the template
    assert b"Take out trash" in response.data
    # Check for something rendered from the weather mock, e.g., current temp
    assert b"70\xc2\xb0" in response.data  # Check for 70° (UTF-8 encoded degree symbol)
    mock_db.add_month.assert_called_once()
    # Check if background task was potentially started (thread initiated)
    mock_thread.assert_called_once()
    call_args, call_kwargs = mock_thread.call_args
    assert call_kwargs["args"] == (5, 2025)  # Check args passed to background task


@patch("src.calendar_app.routes.db")
@patch("src.weather_integration.api.get_weather_data")  # Corrected patch target
@patch("src.calendar_app.routes.threading.Thread")
@patch("src.calendar_app.routes.google_fetch_lock")
@patch("src.calendar_app.routes.background_tasks", new_callable=dict)
@patch("src.calendar_app.routes.last_known_chores", new_callable=list)
def test_view_route_specific_month(
    mock_chores,
    mock_tasks,
    mock_lock,
    mock_thread,
    mock_get_weather,
    mock_db,
    client,  # Updated mock name
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
    # Check if background task was potentially started for Nov 2024
    mock_thread.assert_called_once()
    call_args, call_kwargs = mock_thread.call_args
    assert call_kwargs["args"] == (11, 2024)


def test_view_route_invalid_month(client):
    """Test the calendar view route with an invalid month."""
    response = client.get("/calendar/2024/13")
    assert response.status_code == 404
    assert b"Invalid month" in response.data


# --- Tests for check_updates route ---


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
@patch("src.calendar_app.routes.google_fetch_lock")
@patch("src.calendar_app.routes.background_tasks", new_callable=dict)
def test_check_updates_no_task(
    mock_tasks, mock_lock, mock_sync_photos, client
):  # Updated mock name
    """Test check_updates when the background task is not tracked."""
    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "not_tracked"
    assert not json_data["updates_available"]
    mock_sync_photos.assert_called_once()  # Check slideshow sync is called using updated mock name


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
@patch("src.calendar_app.routes.google_fetch_lock")
@patch("src.calendar_app.routes.background_tasks")
def test_check_updates_task_running(
    mock_tasks, mock_lock, mock_sync_photos, client
):  # Updated mock name
    """Test check_updates when the background task is running."""
    mock_tasks.get.return_value = {"status": "running", "updated": False}
    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "running"
    assert not json_data["updates_available"]
    mock_sync_photos.assert_called_once()  # Use updated mock name


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
@patch("src.calendar_app.routes.google_fetch_lock")
@patch("src.calendar_app.routes.background_tasks")
def test_check_updates_task_complete_with_updates(
    mock_tasks, mock_lock, mock_sync_photos, client
):  # Updated mock name
    """Test check_updates when the task is complete and updates are available."""
    task_info = {
        "status": "complete",
        "updated": True,
        "events_changed": True,
        "chores_changed": False,
    }
    mock_tasks.get.return_value = task_info

    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "complete"
    assert json_data["updates_available"]
    assert json_data["events_changed"]
    assert not json_data["chores_changed"]

    # Verify flags were reset after reading
    assert not task_info["updated"]
    assert not task_info["events_changed"]
    assert not task_info["chores_changed"]
    mock_sync_photos.assert_called_once()


@patch("src.slideshow.database.sync_photos")  # Corrected patch target
@patch("src.calendar_app.routes.google_fetch_lock")
@patch("src.calendar_app.routes.background_tasks")
def test_check_updates_task_complete_no_updates(
    mock_tasks, mock_lock, mock_sync_photos, client
):  # Updated mock name
    """Test check_updates when the task is complete but no updates were found."""
    task_info = {
        "status": "complete",
        "updated": False,
        "events_changed": False,
        "chores_changed": False,
    }
    mock_tasks.get.return_value = task_info

    response = client.get("/calendar/check-updates/2025/5")
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["status"] == "complete"
    assert not json_data["updates_available"]
    assert not json_data["events_changed"]
    assert not json_data["chores_changed"]
    mock_sync_photos.assert_called_once()
