"""Tests for src/google_integration/api.py."""

import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from googleapiclient.errors import HttpError

from src.google_integration.api import (
    _retry_on_error,
    fetch_and_process_google_events,
    get_events_current_month,
    parse_google_datetime,
)


class TestParseGoogleDatetime:
    """Tests for parse_google_datetime."""

    def test_all_day_event(self):
        dt, is_all_day = parse_google_datetime({"date": "2025-05-15"})
        assert is_all_day is True
        assert dt.year == 2025
        assert dt.month == 5
        assert dt.day == 15
        assert dt.tzinfo == datetime.timezone.utc

    def test_datetime_with_z_suffix(self):
        dt, is_all_day = parse_google_datetime({"dateTime": "2025-05-15T10:30:00Z"})
        assert is_all_day is False
        assert dt.hour == 10
        assert dt.minute == 30
        assert dt.tzinfo is not None

    def test_datetime_with_offset(self):
        dt, is_all_day = parse_google_datetime(
            {"dateTime": "2025-05-15T10:30:00-04:00"}
        )
        assert is_all_day is False
        assert dt.tzinfo is not None

    def test_datetime_with_utc_offset(self):
        dt, is_all_day = parse_google_datetime(
            {"dateTime": "2025-05-15T10:30:00+00:00"}
        )
        assert is_all_day is False
        assert dt.hour == 10

    def test_invalid_datetime_fallback(self):
        dt, is_all_day = parse_google_datetime({"dateTime": "not-a-date"})
        assert is_all_day is False
        assert dt == datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


class TestMonthQueryWindow:
    """The Google query window must span the month in local time, not UTC.

    Building it in UTC ended August at 2026-08-31T23:59:59Z, which is only
    19:59:59 in America/New_York, so anything later that evening was never
    fetched for August and only appeared once the user browsed to September.
    """

    TZ = ZoneInfo("America/New_York")

    def _fetch_window(self, month, year):
        """Run get_events_current_month against a mocked service, return window."""
        service = MagicMock()
        service.calendarList().list().execute.return_value = {"items": [{"id": "cal1"}]}
        service.events().list().execute.return_value = {"items": []}

        with patch("src.config.get_local_timezone", return_value=self.TZ):
            get_events_current_month(service, month, year)

        kwargs = service.events().list.call_args.kwargs
        return (
            datetime.datetime.fromisoformat(kwargs["timeMin"]),
            datetime.datetime.fromisoformat(kwargs["timeMax"]),
        )

    def test_window_starts_at_local_midnight_on_the_first(self):
        time_min, _ = self._fetch_window(8, 2026)
        assert time_min == datetime.datetime(2026, 8, 1, 0, 0, tzinfo=self.TZ)
        assert time_min.utcoffset() == datetime.timedelta(hours=-4)

    def test_late_evening_event_on_last_day_is_inside_window(self):
        """The whole point: 10pm on Aug 31 belongs to August's sync window."""
        time_min, time_max = self._fetch_window(8, 2026)
        late_event = datetime.datetime(2026, 8, 31, 22, 0, tzinfo=self.TZ)

        assert time_min <= late_event < time_max

        # ...and the old hardcoded-UTC upper bound would have excluded it.
        old_time_max = datetime.datetime(
            2026, 8, 31, 23, 59, 59, tzinfo=datetime.timezone.utc
        )
        assert late_event > old_time_max

    def test_window_ends_at_local_midnight_starting_the_next_month(self):
        _, time_max = self._fetch_window(8, 2026)
        assert time_max == datetime.datetime(2026, 9, 1, 0, 0, tzinfo=self.TZ)

    def test_window_excludes_previous_month_tail(self):
        """A UTC window reached back into the previous local month."""
        time_min, _ = self._fetch_window(8, 2026)
        prev_month_evening = datetime.datetime(2026, 7, 31, 22, 0, tzinfo=self.TZ)
        assert prev_month_evening < time_min

    def test_window_rolls_over_year_boundary(self):
        time_min, time_max = self._fetch_window(12, 2026)
        assert time_min == datetime.datetime(2026, 12, 1, 0, 0, tzinfo=self.TZ)
        assert time_max == datetime.datetime(2027, 1, 1, 0, 0, tzinfo=self.TZ)

    def test_window_accounts_for_dst_offset_change(self):
        """November in New York starts on EDT and ends on EST."""
        time_min, time_max = self._fetch_window(11, 2026)
        assert time_min.utcoffset() == datetime.timedelta(hours=-4)
        assert time_max.utcoffset() == datetime.timedelta(hours=-5)


def _google_event(event_id, organizer_email=None, start="2026-08-05T09:00:00Z", **kw):
    """Build a raw Google event payload, optionally organised by someone else."""
    event = {
        "id": event_id,
        "summary": kw.get("summary", f"Event {event_id}"),
        "start": {"dateTime": start},
        "end": {"dateTime": start},
    }
    if organizer_email:
        event["organizer"] = {
            "email": organizer_email,
            "displayName": kw.get("organizer_name", f"Organizer {organizer_email}"),
        }
    return event


def _mock_service(calendars, events_by_calendar):
    """A Google Calendar service double serving per-calendar event lists."""
    service = MagicMock()
    service.calendarList().list().execute.return_value = {"items": calendars}

    def list_events(**kwargs):
        request = MagicMock()
        request.execute.return_value = {
            "items": events_by_calendar.get(kwargs["calendarId"], [])
        }
        return request

    service.events().list.side_effect = list_events
    return service


def _process(calendars, events_by_calendar, month=8, year=2026):
    """Run the full fetch+process pipeline against a mocked Google service."""
    service = _mock_service(calendars, events_by_calendar)
    with patch("src.google_integration.api.get_calendar_service", return_value=service):
        return fetch_and_process_google_events(month, year)


class TestEventCalendarAttribution:
    """An event must be attributed to the calendar it was fetched from.

    Attribution used to be read off ``organizer.email``, so an event you were
    invited to by an outsider was filed under that stranger's address: its own
    palette colour, a raw email address for a label, and no chance of a
    ``calendar_aliases.conf`` entry matching it.
    """

    def test_event_attributed_to_source_calendar_not_organizer(self):
        """The core regression: fetched from X, organised by Y -> filed under X."""
        events = _process(
            [{"id": "me@family.test", "summary": "Rasheed", "primary": True}],
            {
                "me@family.test": [
                    _google_event("evt1", organizer_email="stranger@elsewhere.test")
                ]
            },
        )

        assert len(events) == 1
        assert events[0]["calendar_id"] == "me@family.test"
        assert "stranger@elsewhere.test" not in events[0].values()

    def test_display_name_comes_from_calendar_not_organizer(self):
        events = _process(
            [{"id": "me@family.test", "summary": "Rasheed"}],
            {
                "me@family.test": [
                    _google_event(
                        "evt1",
                        organizer_email="stranger@elsewhere.test",
                        organizer_name="Some Stranger",
                    )
                ]
            },
        )

        assert events[0]["calendar_name"] == "Rasheed"

    def test_summary_override_preferred_over_summary(self):
        """A locally renamed shared calendar shows the name the user chose."""
        events = _process(
            [
                {
                    "id": "shared@group.calendar.google.com",
                    "summary": "Bannister Family Shared Calendar",
                    "summaryOverride": "Family",
                }
            ],
            {"shared@group.calendar.google.com": [_google_event("evt1")]},
        )

        assert events[0]["calendar_name"] == "Family"

    def test_summary_used_when_no_override(self):
        events = _process(
            [{"id": "shared@group.calendar.google.com", "summary": "Soccer Team"}],
            {"shared@group.calendar.google.com": [_google_event("evt1")]},
        )

        assert events[0]["calendar_name"] == "Soccer Team"

    def test_calendar_name_falls_back_to_id_when_unnamed(self):
        events = _process(
            [{"id": "unnamed@family.test"}],
            {"unnamed@family.test": [_google_event("evt1")]},
        )

        assert events[0]["calendar_name"] == "unnamed@family.test"

    def test_calendar_without_id_falls_back_to_primary(self):
        events = _process(
            [{"summary": "Mystery calendar"}],
            {"primary": [_google_event("evt1")]},
        )

        assert events[0]["calendar_id"] == "primary"
        assert events[0]["calendar_name"] == "Mystery calendar"

    def test_same_organizer_on_two_calendars_yields_two_calendar_ids(self):
        """Shared organizer must not collapse two calendars into one."""
        organizer = "mum@family.test"
        events = _process(
            [
                {"id": "kids@group.calendar.google.com", "summary": "Kids"},
                {"id": "house@group.calendar.google.com", "summary": "House"},
            ],
            {
                "kids@group.calendar.google.com": [
                    _google_event("evt-kids", organizer_email=organizer)
                ],
                "house@group.calendar.google.com": [
                    _google_event("evt-house", organizer_email=organizer)
                ],
            },
        )

        by_id = {event["id"]: event for event in events}
        assert by_id["evt-kids"]["calendar_id"] == "kids@group.calendar.google.com"
        assert by_id["evt-house"]["calendar_id"] == "house@group.calendar.google.com"
        assert len({event["calendar_id"] for event in events}) == 2
        assert {event["calendar_name"] for event in events} == {"Kids", "House"}

    def test_processed_event_keys_are_unchanged(self):
        """create_calendar_events_from_google_data consumes exactly these keys."""
        events = _process(
            [{"id": "me@family.test", "summary": "Rasheed"}],
            {
                "me@family.test": [
                    {
                        "id": "evt1",
                        "summary": "Dentist",
                        "location": "High Street",
                        "description": "Checkup",
                        "start": {"dateTime": "2026-08-05T09:00:00Z"},
                        "end": {"dateTime": "2026-08-05T10:00:00Z"},
                    }
                ]
            },
        )

        assert set(events[0]) == {
            "id",
            "calendar_id",
            "calendar_name",
            "title",
            "start_datetime",
            "end_datetime",
            "all_day",
            "location",
            "description",
        }
        assert events[0]["title"] == "Dentist"
        assert events[0]["all_day"] is False

    def test_events_still_sorted_by_start_time_across_calendars(self):
        events = _process(
            [
                {"id": "cal-a", "summary": "A"},
                {"id": "cal-b", "summary": "B"},
            ],
            {
                "cal-a": [_google_event("late", start="2026-08-20T09:00:00Z")],
                "cal-b": [
                    _google_event("early", start="2026-08-02T09:00:00Z"),
                    {
                        "id": "allday",
                        "summary": "All day",
                        "start": {"date": "2026-08-10"},
                        "end": {"date": "2026-08-11"},
                    },
                ],
            },
        )

        assert [event["id"] for event in events] == ["early", "allday", "late"]


class TestDuplicateEventAcrossCalendars:
    """The same event id can be visible on several calendars.

    Downstream ``add_events`` does INSERT OR REPLACE on the event id, so before
    this fix the last calendar synced won and the event's colour flapped. The
    event is now emitted once, attributed by calendar precedence: the primary
    calendar first, then lowest calendar id - both stable properties of the
    calendar, never of the order Google listed them in.
    """

    CALENDARS = [
        {"id": "shared@group.calendar.google.com", "summary": "Family"},
        {"id": "me@family.test", "summary": "Rasheed", "primary": True},
    ]

    def _shared_event_on_both(self, calendars):
        return _process(
            calendars,
            {
                "me@family.test": [_google_event("shared-evt")],
                "shared@group.calendar.google.com": [_google_event("shared-evt")],
            },
        )

    def test_duplicate_event_emitted_only_once(self):
        events = self._shared_event_on_both(self.CALENDARS)
        assert len(events) == 1

    def test_duplicate_event_attributed_to_primary_calendar(self):
        events = self._shared_event_on_both(self.CALENDARS)
        assert events[0]["calendar_id"] == "me@family.test"
        assert events[0]["calendar_name"] == "Rasheed"

    def test_attribution_is_stable_regardless_of_calendar_order(self):
        """Reversing the calendar list must not move the event (no colour flap)."""
        forward = self._shared_event_on_both(self.CALENDARS)
        reversed_order = self._shared_event_on_both(list(reversed(self.CALENDARS)))

        assert forward[0]["calendar_id"] == reversed_order[0]["calendar_id"]

    def test_without_primary_lowest_calendar_id_wins_deterministically(self):
        calendars = [
            {"id": "zebra@group.calendar.google.com", "summary": "Zebra"},
            {"id": "alpha@group.calendar.google.com", "summary": "Alpha"},
        ]
        events = _process(
            calendars,
            {
                "zebra@group.calendar.google.com": [_google_event("shared-evt")],
                "alpha@group.calendar.google.com": [_google_event("shared-evt")],
            },
        )
        reversed_events = _process(
            list(reversed(calendars)),
            {
                "zebra@group.calendar.google.com": [_google_event("shared-evt")],
                "alpha@group.calendar.google.com": [_google_event("shared-evt")],
            },
        )

        assert events[0]["calendar_id"] == "alpha@group.calendar.google.com"
        assert reversed_events[0]["calendar_id"] == "alpha@group.calendar.google.com"

    def test_distinct_events_are_not_collapsed(self):
        events = _process(
            self.CALENDARS,
            {
                "me@family.test": [_google_event("mine")],
                "shared@group.calendar.google.com": [_google_event("theirs")],
            },
        )

        assert {event["id"] for event in events} == {"mine", "theirs"}


class TestRetryOnError:
    """Tests for _retry_on_error."""

    def test_success_first_try(self):
        func = MagicMock(return_value="ok")
        result = _retry_on_error(func)
        assert result == "ok"
        assert func.call_count == 1

    def test_retries_on_server_error(self):
        """Should retry on 500 errors."""
        resp = MagicMock()
        resp.status = 500
        error = HttpError(resp, b"Server Error")
        func = MagicMock(side_effect=[error, error, "ok"])

        with patch("src.google_integration.api.time.sleep"):
            result = _retry_on_error(func, retries=3)

        assert result == "ok"
        assert func.call_count == 3

    def test_retries_on_rate_limit(self):
        """Should retry on 429 rate limit errors."""
        resp = MagicMock()
        resp.status = 429
        error = HttpError(resp, b"Rate Limited")
        func = MagicMock(side_effect=[error, "ok"])

        with patch("src.google_integration.api.time.sleep"):
            result = _retry_on_error(func, retries=3)

        assert result == "ok"
        assert func.call_count == 2

    def test_no_retry_on_client_error(self):
        """Should NOT retry on 4xx client errors (except 429)."""
        resp = MagicMock()
        resp.status = 404
        error = HttpError(resp, b"Not Found")
        func = MagicMock(side_effect=error)

        with pytest.raises(HttpError):
            _retry_on_error(func, retries=3)

        assert func.call_count == 1

    def test_raises_after_max_retries(self):
        """Should raise after exhausting all retries."""
        resp = MagicMock()
        resp.status = 500
        error = HttpError(resp, b"Server Error")
        func = MagicMock(side_effect=error)

        with patch("src.google_integration.api.time.sleep"):
            with pytest.raises(HttpError):
                _retry_on_error(func, retries=3)

        assert func.call_count == 3

    def test_retries_on_connection_error(self):
        func = MagicMock(side_effect=[ConnectionError("fail"), "ok"])

        with patch("src.google_integration.api.time.sleep"):
            result = _retry_on_error(func, retries=2)

        assert result == "ok"

    def test_retries_on_timeout_error(self):
        func = MagicMock(side_effect=[TimeoutError("timeout"), "ok"])

        with patch("src.google_integration.api.time.sleep"):
            result = _retry_on_error(func, retries=2)

        assert result == "ok"

    def test_exponential_backoff_timing(self):
        """Verify backoff delays are exponentially increasing."""
        resp = MagicMock()
        resp.status = 500
        error = HttpError(resp, b"Server Error")
        func = MagicMock(side_effect=[error, error, "ok"])

        with patch("src.google_integration.api.time.sleep") as mock_sleep:
            _retry_on_error(func, retries=3)

        # First retry: 1 * 2^0 = 1s, Second retry: 1 * 2^1 = 2s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)
