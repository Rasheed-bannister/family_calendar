"""Tests for src/google_integration/api.py."""

import datetime
import time
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from src.google_integration.api import _retry_on_error, parse_google_datetime


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
        dt, is_all_day = parse_google_datetime(
            {"dateTime": "2025-05-15T10:30:00Z"}
        )
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
        dt, is_all_day = parse_google_datetime(
            {"dateTime": "not-a-date"}
        )
        assert is_all_day is False
        assert dt == datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


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
