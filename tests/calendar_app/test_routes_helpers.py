"""Tests for helper functions in src/calendar_app/routes.py."""

import datetime

from src.calendar_app.routes import (
    _build_calendar_weeks_data,
    _calculate_navigation_dates,
    _is_event_relevant_for_date,
    _is_midnight_end,
    _is_multi_day_event_relevant,
    _is_single_day_event_relevant,
    _normalize_event_timezone,
)


class TestCalculateNavigationDates:
    """Tests for _calculate_navigation_dates."""

    def test_mid_year(self):
        prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
            2025, 6
        )
        assert (prev_year, prev_month) == (2025, 5)
        assert (next_year, next_month) == (2025, 7)

    def test_january_wraps_to_december(self):
        prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
            2025, 1
        )
        assert (prev_year, prev_month) == (2024, 12)
        assert (next_year, next_month) == (2025, 2)

    def test_december_wraps_to_january(self):
        prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
            2025, 12
        )
        assert (prev_year, prev_month) == (2025, 11)
        assert (next_year, next_month) == (2026, 1)

    def test_february(self):
        prev_year, prev_month, next_year, next_month = _calculate_navigation_dates(
            2025, 2
        )
        assert (prev_year, prev_month) == (2025, 1)
        assert (next_year, next_month) == (2025, 3)


class TestIsMidnightEnd:
    """Tests for _is_midnight_end."""

    def test_midnight(self):
        dt = datetime.datetime(2025, 5, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)
        assert _is_midnight_end(dt) is True

    def test_not_midnight(self):
        dt = datetime.datetime(2025, 5, 15, 10, 30, 0, tzinfo=datetime.timezone.utc)
        assert _is_midnight_end(dt) is False

    def test_midnight_with_seconds(self):
        dt = datetime.datetime(2025, 5, 15, 0, 0, 1, tzinfo=datetime.timezone.utc)
        assert _is_midnight_end(dt) is False


class TestIsSingleDayEventRelevant:
    """Tests for _is_single_day_event_relevant."""

    def test_same_day(self):
        date = datetime.date(2025, 5, 15)
        assert _is_single_day_event_relevant(date, date, date) is True

    def test_different_day(self):
        start = datetime.date(2025, 5, 15)
        target = datetime.date(2025, 5, 16)
        assert _is_single_day_event_relevant(start, start, target) is False


class TestIsMultiDayEventRelevant:
    """Tests for _is_multi_day_event_relevant."""

    def test_target_in_range(self):
        start = datetime.date(2025, 5, 10)
        end = datetime.date(2025, 5, 20)
        target = datetime.date(2025, 5, 15)
        assert _is_multi_day_event_relevant(start, end, target, False) is True

    def test_target_on_start(self):
        start = datetime.date(2025, 5, 10)
        end = datetime.date(2025, 5, 20)
        assert _is_multi_day_event_relevant(start, end, start, False) is True

    def test_target_on_end_not_midnight(self):
        start = datetime.date(2025, 5, 10)
        end = datetime.date(2025, 5, 20)
        assert _is_multi_day_event_relevant(start, end, end, False) is True

    def test_target_on_end_midnight_excluded(self):
        """Events ending at midnight shouldn't show on their end date."""
        start = datetime.date(2025, 5, 10)
        end = datetime.date(2025, 5, 20)
        assert _is_multi_day_event_relevant(start, end, end, True) is False

    def test_target_outside_range(self):
        start = datetime.date(2025, 5, 10)
        end = datetime.date(2025, 5, 20)
        target = datetime.date(2025, 5, 25)
        assert _is_multi_day_event_relevant(start, end, target, False) is False


class TestNormalizeEventTimezone:
    """Tests for _normalize_event_timezone."""

    def test_with_timezone(self):
        event = {
            "start_datetime": datetime.datetime(
                2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            "end_datetime": datetime.datetime(
                2025, 5, 15, 11, 0, 0, tzinfo=datetime.timezone.utc
            ),
        }
        start, end = _normalize_event_timezone(event)
        assert start.tzinfo is not None
        assert end.tzinfo is not None

    def test_naive_datetimes_get_utc(self):
        event = {
            "start_datetime": datetime.datetime(2025, 5, 15, 10, 0, 0),
            "end_datetime": datetime.datetime(2025, 5, 15, 11, 0, 0),
        }
        start, end = _normalize_event_timezone(event)
        assert start.tzinfo == datetime.timezone.utc
        assert end.tzinfo == datetime.timezone.utc


class TestIsEventRelevantForDate:
    """Tests for _is_event_relevant_for_date."""

    def test_single_day_event_on_target(self):
        event = {
            "start_datetime": datetime.datetime(
                2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            "end_datetime": datetime.datetime(
                2025, 5, 15, 11, 0, 0, tzinfo=datetime.timezone.utc
            ),
        }
        assert _is_event_relevant_for_date(event, datetime.date(2025, 5, 15)) is True
        assert _is_event_relevant_for_date(event, datetime.date(2025, 5, 16)) is False

    def test_multi_day_event(self):
        event = {
            "start_datetime": datetime.datetime(
                2025, 5, 10, 10, 0, 0, tzinfo=datetime.timezone.utc
            ),
            "end_datetime": datetime.datetime(
                2025, 5, 12, 15, 0, 0, tzinfo=datetime.timezone.utc
            ),
        }
        assert _is_event_relevant_for_date(event, datetime.date(2025, 5, 11)) is True
        assert _is_event_relevant_for_date(event, datetime.date(2025, 5, 9)) is False

    def test_all_day_event_ends_midnight_next_day(self):
        """All-day events from Google end at midnight of next day."""
        event = {
            "start_datetime": datetime.datetime(
                2025, 5, 15, 0, 0, 0, tzinfo=datetime.timezone.utc
            ),
            "end_datetime": datetime.datetime(
                2025, 5, 16, 0, 0, 0, tzinfo=datetime.timezone.utc
            ),
        }
        assert _is_event_relevant_for_date(event, datetime.date(2025, 5, 15)) is True
        # Should NOT show on the 16th since it ends at midnight
        assert _is_event_relevant_for_date(event, datetime.date(2025, 5, 16)) is False


class TestBuildCalendarWeeksData:
    """Tests for _build_calendar_weeks_data."""

    def test_basic_month_structure(self):
        today = datetime.date(2025, 5, 15)
        weeks = _build_calendar_weeks_data(2025, 5, today, [])
        assert len(weeks) > 0
        # Each week should have 7 days
        for week in weeks:
            assert len(week) == 7

    def test_today_is_marked(self):
        today = datetime.date(2025, 5, 15)
        weeks = _build_calendar_weeks_data(2025, 5, today, [])
        found_today = False
        for week in weeks:
            for day in week:
                if day["day_number"] == 15 and day["is_today"]:
                    found_today = True
        assert found_today

    def test_today_not_in_month(self):
        """When viewing a different month, no day should be marked as today."""
        today = datetime.date(2025, 6, 15)  # June
        weeks = _build_calendar_weeks_data(2025, 5, today, [])  # Viewing May
        for week in weeks:
            for day in week:
                assert day["is_today"] is False

    def test_empty_days_have_no_number(self):
        """Days from other months should have empty day_number."""
        today = datetime.date(2025, 5, 15)
        weeks = _build_calendar_weeks_data(2025, 5, today, [])
        # May 2025 starts on Thursday, so first 4 days should be empty (Sun-Wed)
        first_week = weeks[0]
        assert first_week[0]["day_number"] == ""  # Sunday
        assert first_week[0]["is_current_month"] is False

    def test_events_attached_to_correct_day(self):
        today = datetime.date(2025, 5, 15)
        events = [
            {
                "start_datetime": datetime.datetime(
                    2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
                ),
                "end_datetime": datetime.datetime(
                    2025, 5, 15, 11, 0, 0, tzinfo=datetime.timezone.utc
                ),
                "all_day": False,
            }
        ]
        weeks = _build_calendar_weeks_data(2025, 5, today, events)
        found = False
        for week in weeks:
            for day in week:
                if day["day_number"] == 15:
                    assert len(day["events"]) == 1
                    found = True
        assert found
