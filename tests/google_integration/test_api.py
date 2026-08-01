"""Tests for src/google_integration/api.py."""

import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from googleapiclient.errors import HttpError

from src.google_integration.api import (
    _retry_on_error,
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
