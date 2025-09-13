import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from src.calendar_app import database as db
from src.calendar_app import utils
from src.calendar_app.models import Calendar, CalendarEvent, CalendarMonth

# --- Fixtures ---


@pytest.fixture
def mock_db_connection():
    """Provides a mock database connection and cursor."""
    mock_conn = MagicMock(spec=sqlite3.Connection)
    mock_cursor = MagicMock(spec=sqlite3.Cursor)
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None
    return mock_conn, mock_cursor


@pytest.fixture
def sample_calendar():
    """Provides a sample Calendar object."""
    return Calendar(calendar_id="cal1", name="Test Calendar", color_hex="#FFFFFF")


@pytest.fixture
def sample_month():
    """Provides a sample CalendarMonth object."""
    month = CalendarMonth(year=2025, month=5)
    month.id = 1
    return month


@pytest.fixture
def sample_event(sample_calendar, sample_month):
    """Provides a sample CalendarEvent object."""
    return CalendarEvent(
        id="event1",
        calendar=sample_calendar,
        month=sample_month,
        title="Test Event 1",
        start_datetime=datetime(2025, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 5, 10, 11, 0, 0, tzinfo=timezone.utc),
        all_day=False,
        location="Location 1",
        description="Description 1",
    )


@pytest.fixture
def sample_event_list(sample_calendar, sample_month):
    """Provides a list of sample CalendarEvent objects."""
    event1 = CalendarEvent(
        id="event1",
        calendar=sample_calendar,
        month=sample_month,
        title="Event 1",
        start_datetime=datetime(2025, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 5, 10, 11, 0, 0, tzinfo=timezone.utc),
        all_day=False,
    )
    event2 = CalendarEvent(
        id="event2",
        calendar=sample_calendar,
        month=sample_month,
        title="Event 2",
        start_datetime=datetime(2025, 5, 11, 14, 0, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 5, 11, 15, 0, 0, tzinfo=timezone.utc),
        all_day=False,
    )
    # Event with missing calendar color initially
    calendar_no_color = Calendar(
        calendar_id="cal_no_color", name="Needs Color", color_hex=None
    )
    event3 = CalendarEvent(
        id="event3",
        calendar=calendar_no_color,
        month=sample_month,
        title="Event 3 Needs Color",
        start_datetime=datetime(2025, 5, 12, 9, 0, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 5, 12, 9, 30, 0, tzinfo=timezone.utc),
        all_day=False,
    )
    return [event1, event2, event3]


@pytest.fixture
def sample_google_data():
    """Provides sample processed Google event data."""
    return [
        {
            "id": "google_event1",
            "calendar_id": "google_cal1",
            "calendar_name": "Google Calendar 1",
            "title": "Google Event 1",
            "start_datetime": datetime(2025, 5, 15, 9, 0, 0, tzinfo=timezone.utc),
            "end_datetime": datetime(2025, 5, 15, 10, 0, 0, tzinfo=timezone.utc),
            "all_day": False,
            "location": "Google Location",
            "description": "Google Desc",
        },
        {
            "id": "google_event2",
            "calendar_id": "google_cal2",
            "calendar_name": "Google Calendar 2",
            "title": "Google Event 2 (All Day)",
            "start_datetime": datetime(
                2025, 5, 16, 0, 0, 0, tzinfo=timezone.utc
            ),  # Often midnight for all-day
            "end_datetime": datetime(
                2025, 5, 17, 0, 0, 0, tzinfo=timezone.utc
            ),  # Often midnight next day
            "all_day": True,
            # Mocking a missing location/description
        },
        {
            "id": "google_event3_update_name",
            "calendar_id": "existing_cal_id",  # Assume this calendar exists but name changes
            "calendar_name": "Updated Calendar Name",
            "title": "Event on Existing Calendar",
            "start_datetime": datetime(2025, 5, 17, 11, 0, 0, tzinfo=timezone.utc),
            "end_datetime": datetime(2025, 5, 17, 12, 0, 0, tzinfo=timezone.utc),
            "all_day": False,
        },
    ]


# --- Mocks for Database Interactions ---


@patch("src.calendar_app.database.sqlite3.connect")
@patch("src.calendar_app.utils.db")
@patch("src.calendar_app.utils.get_next_color")
def test_add_events_inserts_new(
    mock_get_next_color,
    mock_db_module,
    mock_sqlite_connect,
    mock_db_connection,
    sample_event_list,
):
    """Test that add_events correctly inserts events that don't exist."""
    mock_conn, mock_cursor = mock_db_connection
    mock_sqlite_connect.return_value = mock_conn
    mocked_color = "#ABCDEF"
    mock_get_next_color.return_value = mocked_color  # Mock color assignment

    # Configure side_effect for fetchone to handle multiple calls:
    # 1. Event 1 check: Not found (None)
    # 2. Event 2 check: Not found (None)
    # 3. Event 3 check: Not found (None)
    # --- Inside get_next_color (called for event 3) ---
    # 4. SELECT current_index: Return index 0
    # 5. SELECT COUNT(*): Return 10 colors
    # 6. SELECT hex_code: Return the mocked color
    mock_cursor.fetchone.side_effect = [
        None,  # Event 1 exists check
        None,  # Event 2 exists check
        None,  # Event 3 exists check
        (0,),  # get_next_color: current_index
        (10,),  # get_next_color: color_count
        (mocked_color,),  # get_next_color: hex_code
    ]

    # Call the function *without* the cursor - the decorator provides it
    result = utils.add_events(sample_event_list)

    assert result is True  # Changes should have been made
    mock_sqlite_connect.assert_called_once_with(db.DATABASE_FILE)
    mock_conn.commit.assert_called_once()  # Verify commit was called by decorator
    mock_conn.close.assert_called_once()  # Verify close was called by decorator

    # Verify INSERT OR REPLACE was called for each event
    insert_calls = []
    for event in sample_event_list:
        # Check if calendar color needed assignment (event3)
        if event.id == "event3":
            # Check calendar insert/replace first
            insert_calls.append(
                call(
                    "INSERT OR REPLACE INTO Calendar (calendar_id, name, color) VALUES (?, ?, ?)",
                    (
                        event.calendar.calendar_id,
                        event.calendar.name,
                        mocked_color,
                    ),  # Expected assigned color
                )
            )
        # Check event insert/replace
        insert_calls.append(
            call(
                """
                INSERT OR REPLACE INTO CalendarEvent (
                    id, calendar_id, month_id,
                    title, start_datetime, end_datetime,
                    all_day, location, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.calendar.calendar_id,
                    event.month.id,
                    event.title,
                    event.start.isoformat(),
                    event.end.isoformat(),
                    event.all_day,
                    event.location,
                    event.description,
                ),
            )
        )

    # Check that all expected execute calls happened (SELECTs and INSERTs)
    # Use any_order=True because SELECTs and get_next_color calls are interspersed
    mock_cursor.execute.assert_has_calls(insert_calls, any_order=True)

    # Verify get_next_color was called with the cursor provided by the decorator
    mock_get_next_color.assert_called_once_with(cursor=mock_cursor)


@patch(
    "src.calendar_app.utils.db"
)  # Mock the db module alias used in create_calendar_events...
def test_create_calendar_events_new_calendar(
    mock_db_module, sample_google_data, sample_month
):
    """Test creating events when the calendar is new."""
    google_data_new_cal = [sample_google_data[0]]  # Use only the first event
    new_cal_id = google_data_new_cal[0]["calendar_id"]
    new_cal_name = google_data_new_cal[0]["calendar_name"]
    assigned_color = "#123456"

    # Mock db.get_calendar to return None initially, then the created calendar
    # Corrected: Create mock with color_hex if simulating color assignment by add_calendar
    # Simulate that add_calendar assigned a color and get_calendar returns it
    created_calendar_mock = Calendar(
        calendar_id=new_cal_id, name=new_cal_name, color_hex=assigned_color
    )
    mock_db_module.get_calendar.side_effect = [
        None,
        created_calendar_mock,
    ]  # First call returns None, second returns the object with color
    mock_db_module.add_calendar.return_value = (
        None  # Doesn't need to return anything specific
    )

    events, calendars_changed = utils.create_calendar_events_from_google_data(
        google_data_new_cal, sample_month
    )

    assert calendars_changed is True
    assert len(events) == 1
    event = events[0]
    assert event.id == google_data_new_cal[0]["id"]
    assert event.calendar.calendar_id == new_cal_id
    assert event.calendar.name == new_cal_name
    # Assertion should now pass as event.calendar is created_calendar_mock with color
    assert event.calendar.color == assigned_color
    assert event.month == sample_month
    assert event.title == google_data_new_cal[0]["title"]

    # Verify db interactions
    mock_db_module.get_calendar.assert_has_calls([call(new_cal_id), call(new_cal_id)])
    mock_db_module.add_calendar.assert_called_once()
    # Check the object passed to add_calendar (before color is assigned by get_next_color logic)
    added_calendar_arg = mock_db_module.add_calendar.call_args[0][0]
    assert isinstance(added_calendar_arg, Calendar)
    assert added_calendar_arg.calendar_id == new_cal_id
    assert added_calendar_arg.name == new_cal_name
    # add_calendar receives the object potentially without color, it assigns it internally
    assert added_calendar_arg.color is None


@patch("src.calendar_app.utils.db")
def test_create_calendar_events_existing_calendar_name_change(
    mock_db_module, sample_google_data, sample_month
):
    """Test creating events when the calendar exists but its name needs updating."""
    google_data_update_cal = [sample_google_data[2]]  # Use the third event
    existing_cal_id = google_data_update_cal[0]["calendar_id"]
    original_name = "Old Calendar Name"
    updated_name = google_data_update_cal[0]["calendar_name"]
    existing_color = "#EXIST"

    # Mock db.get_calendar to return the existing calendar, then the updated one
    existing_calendar_mock = Calendar(
        calendar_id=existing_cal_id, name=original_name, color_hex=existing_color
    )
    # Simulate the state after add_calendar updates the name but keeps the color
    updated_calendar_mock = Calendar(
        calendar_id=existing_cal_id, name=updated_name, color_hex=existing_color
    )

    mock_db_module.get_calendar.side_effect = [
        existing_calendar_mock,
        updated_calendar_mock,
    ]
    mock_db_module.add_calendar.return_value = None

    events, calendars_changed = utils.create_calendar_events_from_google_data(
        google_data_update_cal, sample_month
    )

    assert calendars_changed is True
    assert len(events) == 1
    event = events[0]
    assert event.id == google_data_update_cal[0]["id"]
    assert event.calendar.calendar_id == existing_cal_id
    assert event.calendar.name == updated_name  # Name should be updated
    # Assertion should now pass
    assert event.calendar.color == existing_color  # Color should be preserved

    # Verify db interactions
    mock_db_module.get_calendar.assert_has_calls(
        [call(existing_cal_id), call(existing_cal_id)]
    )
    mock_db_module.add_calendar.assert_called_once()
    # Check the object passed to add_calendar
    added_calendar_arg = mock_db_module.add_calendar.call_args[0][0]
    assert isinstance(added_calendar_arg, Calendar)
    assert added_calendar_arg.calendar_id == existing_cal_id
    assert (
        added_calendar_arg.name == updated_name
    )  # Updated name passed to add_calendar
    # add_calendar receives the object with the existing color when updating
    assert added_calendar_arg.color == existing_color


@patch("src.calendar_app.utils.db")
def test_create_calendar_events_existing_calendar_no_change(
    mock_db_module, sample_google_data, sample_month
):
    """Test creating events when the calendar exists and needs no update."""
    # Use data where calendar name matches existing mock
    google_data_no_change = [sample_google_data[0].copy()]  # Copy to modify
    existing_cal_id = google_data_no_change[0]["calendar_id"]
    existing_name = "Google Calendar 1"
    existing_color = "#EXIST"

    # Mock db.get_calendar to return the existing calendar consistently
    existing_calendar_mock = Calendar(
        calendar_id=existing_cal_id, name=existing_name, color_hex=existing_color
    )
    mock_db_module.get_calendar.return_value = (
        existing_calendar_mock  # Always return the same object
    )

    events, calendars_changed = utils.create_calendar_events_from_google_data(
        google_data_no_change, sample_month
    )

    assert calendars_changed is False  # No calendar changes expected
    assert len(events) == 1
    event = events[0]
    assert event.id == google_data_no_change[0]["id"]
    assert (
        event.calendar == existing_calendar_mock
    )  # Should use the exact object returned by get_calendar
    assert event.calendar.color == existing_color  # Verify color is correct

    # Verify db interactions
    mock_db_module.get_calendar.assert_called_once_with(existing_cal_id)
    mock_db_module.add_calendar.assert_not_called()  # add_calendar should not be called


@patch("src.calendar_app.database.run_migrations")
@patch("src.calendar_app.database.DATABASE_FILE")
@patch("src.calendar_app.database.create_all")
def test_initialize_db_creates_if_not_exists(
    mock_create_all, mock_db_file, mock_migrations
):
    """Test initialize_db calls create_all when the DB file doesn't exist."""
    mock_db_file.exists.return_value = False
    utils.initialize_db()
    mock_create_all.assert_called_once()
    mock_migrations.assert_called_once()


@patch("src.calendar_app.database.run_migrations")
@patch("src.calendar_app.database.DATABASE_FILE")
@patch("src.calendar_app.database.create_all")
def test_initialize_db_does_nothing_if_exists(
    mock_create_all, mock_db_file, mock_migrations
):
    """Test initialize_db does nothing when the DB file already exists."""
    mock_db_file.exists.return_value = True
    utils.initialize_db()
    mock_create_all.assert_not_called()
    mock_migrations.assert_called_once()  # Migrations always run


# Test updates using INSERT OR REPLACE
@patch("src.calendar_app.database.sqlite3.connect")
@patch("src.calendar_app.utils.db")  # Mock db module for calendar checks if needed
@patch("src.calendar_app.utils.get_next_color")  # Mock color assignment if needed
def test_add_events_updates_existing(
    mock_get_next_color,
    mock_db_module,
    mock_sqlite_connect,
    mock_db_connection,
    sample_event,
    sample_calendar,
    sample_month,
):
    """Test that add_events updates events using INSERT OR REPLACE."""
    mock_conn, mock_cursor = mock_db_connection
    mock_sqlite_connect.return_value = mock_conn
    mock_get_next_color.return_value = (
        "#NEWCOLOR"  # In case calendar color needs update
    )

    # --- Test Case Data ---
    # Use unique IDs for each update type test
    original_start = datetime(2025, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    original_end = datetime(2025, 5, 20, 11, 0, 0, tzinfo=timezone.utc)

    # 1. Update Start Time
    updated_start_event = CalendarEvent(
        id="event_update_start",  # Unique ID
        calendar=sample_calendar,
        month=sample_month,
        title="Updated Start Event",
        start_datetime=datetime(2025, 5, 20, 10, 30, 0, tzinfo=timezone.utc),  # Changed
        end_datetime=original_end,
        all_day=False,
    )

    # 2. Update End Time
    updated_end_event = CalendarEvent(
        id="event_update_end",  # Unique ID
        calendar=sample_calendar,
        month=sample_month,
        title="Updated End Event",
        start_datetime=original_start,
        end_datetime=datetime(2025, 5, 20, 11, 30, 0, tzinfo=timezone.utc),  # Changed
        all_day=False,
    )

    # 3. Update All Day Flag
    updated_all_day_event = CalendarEvent(
        id="event_update_allday",  # Unique ID
        calendar=sample_calendar,
        month=sample_month,
        title="Updated All Day Event",
        start_datetime=datetime(2025, 5, 21, 0, 0, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2025, 5, 22, 0, 0, 0, tzinfo=timezone.utc),
        all_day=True,  # Changed
    )

    # 4. Update Both Start and End Times
    updated_both_event = CalendarEvent(
        id="event_update_both",  # Unique ID
        calendar=sample_calendar,
        month=sample_month,
        title="Updated Both Times Event",
        start_datetime=datetime(2025, 5, 20, 14, 0, 0, tzinfo=timezone.utc),  # Changed
        end_datetime=datetime(2025, 5, 20, 15, 0, 0, tzinfo=timezone.utc),  # Changed
        all_day=False,
    )

    events_to_test = [
        updated_start_event,
        updated_end_event,
        updated_all_day_event,
        updated_both_event,
    ]

    # --- Run Test ---
    mock_cursor.fetchone.side_effect = None  # Reset side effect if any
    mock_cursor.fetchone.return_value = None  # Default return if needed elsewhere

    result = utils.add_events(events_to_test)

    # --- Assertions ---
    assert result is True  # Changes should have been made
    mock_sqlite_connect.assert_called_once_with(db.DATABASE_FILE)
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()

    # Verify INSERT OR REPLACE was called for each updated event
    expected_calls = []
    for event in events_to_test:
        # Check if calendar color needed update (unlikely here, but for completeness)
        if not event.calendar.color:
            expected_calls.append(
                call(
                    "INSERT OR REPLACE INTO Calendar (calendar_id, name, color) VALUES (?, ?, ?)",
                    (
                        event.calendar.calendar_id,
                        event.calendar.name,
                        mock_get_next_color.return_value,
                    ),
                )
            )

        expected_calls.append(
            call(
                """
                INSERT OR REPLACE INTO CalendarEvent (
                    id, calendar_id, month_id,
                    title, start_datetime, end_datetime,
                    all_day, location, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.calendar.calendar_id,
                    event.month.id,
                    event.title,
                    event.start.isoformat(),
                    event.end.isoformat(),
                    event.all_day,
                    event.location,
                    event.description,
                ),
            )
        )

    # Check that all expected execute calls happened
    # Use any_order=True as calendar updates might intersperse
    mock_cursor.execute.assert_has_calls(expected_calls, any_order=True)

    # Verify execute was called the correct number of times (once per event + maybe calendar updates)
    assert mock_cursor.execute.call_count == len(expected_calls)

    # Verify get_next_color was not called if sample_calendar has color
    if sample_calendar.color:
        mock_get_next_color.assert_not_called()
    else:
        # Add assertion for calls if sample_calendar might not have color
        pass
