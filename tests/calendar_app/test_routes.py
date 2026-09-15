import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src import sync_state

# Import the functions/blueprint to test
from src.calendar_app import routes as calendar_routes

# Import the app factory function
from src.main import create_app

# Background sync state lives in the registry; it is the single seam the tests
# patch, so production code and assertions can never read different dicts.
from src.sync_state import registry

CALENDAR_TASK_ID = "calendar.5.2025"
NY = ZoneInfo("America/New_York")


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


# --- Tests for the JSON month/day API ---


def _event(
    event_id="ev1",
    title="Dentist",
    start=datetime.datetime(2025, 5, 15, 14, 0, tzinfo=datetime.timezone.utc),
    end=datetime.datetime(2025, 5, 15, 15, 0, tzinfo=datetime.timezone.utc),
    all_day=False,
    **extra,
):
    return {
        "google_event_id": event_id,
        "title": title,
        "start_datetime": start,
        "end_datetime": end,
        "all_day": all_day,
        "location": extra.get("location"),
        "description": extra.get("description"),
        "calendar_name": extra.get("calendar_name", "Family"),
        "calendar_color": extra.get("calendar_color", "#123456"),
    }


@pytest.fixture
def local_tz():
    with patch("src.config.get_local_timezone", return_value=NY):
        yield NY


@pytest.fixture
def fixed_now(local_tz):
    now = datetime.datetime(2025, 5, 2, 12, 0, tzinfo=NY)
    with patch("src.calendar_app.routes.datetime") as mock_dt:
        mock_dt.datetime.now.return_value = now
        mock_dt.date = datetime.date
        mock_dt.timezone = datetime.timezone
        mock_dt.timedelta = datetime.timedelta
        yield now


class TestSerializeEvent:
    def test_instants_are_expressed_in_the_display_timezone(self):
        data = calendar_routes.serialize_event(_event(), NY)
        assert data["start"] == "2025-05-15T10:00:00-04:00"
        assert data["end"] == "2025-05-15T11:00:00-04:00"
        assert data["id"] == "ev1"
        assert data["color"] == "#123456"
        assert data["calendar_name"] == "Family"
        assert data["all_day"] is False
        assert data["location"] == ""
        assert data["description"] == ""

    def test_naive_datetimes_are_treated_as_utc(self):
        data = calendar_routes.serialize_event(
            _event(
                start=datetime.datetime(2025, 5, 15, 14, 0),
                end=datetime.datetime(2025, 5, 15, 15, 0),
            ),
            NY,
        )
        assert data["start"] == "2025-05-15T10:00:00-04:00"

    def test_missing_calendar_gets_defaults(self):
        event = _event(calendar_name=None, calendar_color=None)
        data = calendar_routes.serialize_event(event, NY)
        assert data["calendar_name"] == "Unknown Calendar"
        assert data["color"] == "#808080"


class TestBuildMonthPayload:
    def test_shape(self):
        today = datetime.date(2025, 5, 15)
        payload = calendar_routes.build_month_payload(2025, 5, today, [_event()], NY)
        assert payload["year"] == 2025
        assert payload["month"] == 5
        assert payload["month_name"] == "May"
        assert payload["today"] == "2025-05-15"
        assert payload["prev"] == {"year": 2025, "month": 4}
        assert payload["next"] == {"year": 2025, "month": 6}
        assert all(len(week) == 7 for week in payload["weeks"])
        # May 2025 starts on a Thursday: Sun-Wed of the first week are padding.
        assert payload["weeks"][0][:4] == [None] * 4
        cell = payload["weeks"][0][4]
        assert cell["date"] == "2025-05-01"
        assert cell["day"] == 1
        assert cell["is_today"] is False
        assert cell["events"] == []

    def test_events_land_on_their_day_and_today_is_marked(self):
        today = datetime.date(2025, 5, 15)
        payload = calendar_routes.build_month_payload(2025, 5, today, [_event()], NY)
        cells = [c for week in payload["weeks"] for c in week if c]
        fifteenth = next(c for c in cells if c["day"] == 15)
        assert fifteenth["is_today"] is True
        assert [e["title"] for e in fifteenth["events"]] == ["Dentist"]
        assert sum(len(c["events"]) for c in cells) == 1

    def test_multi_day_event_appears_on_every_day(self):
        event = _event(
            start=datetime.datetime(2025, 5, 10, 9, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2025, 5, 12, 17, 0, tzinfo=datetime.timezone.utc),
        )
        payload = calendar_routes.build_month_payload(
            2025, 5, datetime.date(2025, 5, 1), [event], NY
        )
        days = sorted(
            c["day"] for week in payload["weeks"] for c in week if c and c["events"]
        )
        assert days == [10, 11, 12]


class TestMonthApi:
    @patch("src.calendar_app.routes.db")
    def test_returns_month_and_queues_a_sync(
        self, mock_db, client, tasks_state, mock_executor, fixed_now
    ):
        mock_db.get_all_events_for_month_range.return_value = [_event()]

        response = client.get("/api/calendar/2025/5")

        assert response.status_code == 200
        data = response.get_json()
        assert data["month_name"] == "May"
        assert data["today"] == "2025-05-02"
        mock_db.add_month.assert_called_once()
        mock_db.get_all_events_for_month_range.assert_called_once_with(2025, 5)
        # Exactly one thing is queued: the calendar sync for this month. No
        # chores sync piggybacks on a month fetch any more.
        assert mock_executor.submit.call_count == 1
        assert mock_executor.submit.call_args[0][1:] == (5, 2025)
        assert data["sync_status"] == sync_state.PENDING

    @patch("src.calendar_app.routes.db")
    def test_sync_can_be_suppressed(
        self, mock_db, client, tasks_state, mock_executor, fixed_now
    ):
        mock_db.get_all_events_for_month_range.return_value = []
        response = client.get("/api/calendar/2025/5?sync=0")
        assert response.status_code == 200
        mock_executor.submit.assert_not_called()
        assert response.get_json()["sync_status"] is None

    @patch("src.calendar_app.routes.db")
    def test_fresh_month_is_not_resynced(
        self, mock_db, client, tasks_state, mock_executor, fixed_now
    ):
        """Re-fetching on every change notification must not feed back into syncs."""
        import time

        mock_db.get_all_events_for_month_range.return_value = []
        tasks_state[CALENDAR_TASK_ID] = {
            "status": sync_state.COMPLETE,
            "last_update_time": time.time(),
        }
        client.get("/api/calendar/2025/5")
        client.get("/api/calendar/2025/5")
        mock_executor.submit.assert_not_called()

    @patch("src.calendar_app.routes.db")
    def test_other_month_has_no_today_cell(
        self, mock_db, client, tasks_state, mock_executor, fixed_now
    ):
        mock_db.get_all_events_for_month_range.return_value = []
        data = client.get("/api/calendar/2025/6").get_json()
        assert data["today"] == "2025-05-02"
        assert not any(c and c["is_today"] for week in data["weeks"] for c in week)

    @pytest.mark.parametrize(
        "path",
        ["/api/calendar/2025/13", "/api/calendar/2025/0", "/api/calendar/1900/5"],
    )
    def test_invalid_month_is_404(self, client, path):
        response = client.get(path)
        assert response.status_code == 404
        assert response.get_json()["error"]

    def test_old_html_urls_redirect_to_the_app(self, client):
        response = client.get("/calendar/2025/5")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/?year=2025&month=5")
        assert client.get("/calendar/").status_code == 302
        assert client.get("/calendar/fragment/2025/5").status_code == 404
        assert client.get("/calendar/check-updates/2025/5").status_code == 404


class TestDayApi:
    @patch("src.calendar_app.routes.db")
    def test_returns_events_for_the_day(self, mock_db, client, local_tz):
        mock_db.get_all_events_for_month_range.return_value = [
            _event(),
            _event(
                event_id="ev2",
                title="Tomorrow",
                start=datetime.datetime(
                    2025, 5, 16, 14, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(2025, 5, 16, 15, 0, tzinfo=datetime.timezone.utc),
            ),
        ]
        data = client.get("/api/calendar/day/2025-05-15").get_json()
        assert data["date"] == "2025-05-15"
        assert [e["id"] for e in data["events"]] == ["ev1"]
        mock_db.get_all_events_for_month_range.assert_called_once_with(2025, 5)

    def test_invalid_date_is_404(self, client):
        assert client.get("/api/calendar/day/2025-13-99").status_code == 404
        assert client.get("/api/calendar/day/yesterday").status_code == 404
