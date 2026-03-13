"""Tests for src/calendar_app/models.py."""

import datetime

from src.calendar_app.models import Calendar, CalendarEvent, CalendarMonth


class TestCalendarMonth:
    """Tests for CalendarMonth model."""

    def test_id_format(self):
        month = CalendarMonth(year=2025, month=5)
        assert month.id == "5.2025"

    def test_attributes(self):
        month = CalendarMonth(year=2025, month=12)
        assert month.year == 2025
        assert month.month == 12

    def test_repr(self):
        month = CalendarMonth(year=2025, month=5)
        assert "2025" in repr(month)
        assert "5" in repr(month)


class TestCalendar:
    """Tests for Calendar model."""

    def test_display_name_fallback(self):
        cal = Calendar(calendar_id="c1", name="My Calendar")
        assert cal.display_name == "My Calendar"  # Falls back to name

    def test_display_name_explicit(self):
        cal = Calendar(calendar_id="c1", name="My Calendar", display_name="Custom Name")
        assert cal.display_name == "Custom Name"

    def test_get_display_name(self):
        cal = Calendar(calendar_id="c1", name="Name", display_name="Display")
        assert cal.get_display_name() == "Display"

    def test_get_display_name_fallback(self):
        cal = Calendar(calendar_id="c1", name="Name", display_name=None)
        # display_name defaults to name in __init__
        assert cal.get_display_name() == "Name"

    def test_color_optional(self):
        cal = Calendar(calendar_id="c1", name="Name")
        assert cal.color is None


class TestCalendarEvent:
    """Tests for CalendarEvent model."""

    def test_attributes(self):
        cal = Calendar(calendar_id="c1", name="Cal")
        month = CalendarMonth(year=2025, month=5)
        event = CalendarEvent(
            id="e1",
            calendar=cal,
            month=month,
            title="Test",
            start_datetime=datetime.datetime(2025, 5, 15, 10, 0),
            end_datetime=datetime.datetime(2025, 5, 15, 11, 0),
            all_day=False,
            location="Here",
            description="Desc",
        )
        assert event.id == "e1"
        assert event.title == "Test"
        assert event.start == datetime.datetime(2025, 5, 15, 10, 0)
        assert event.end == datetime.datetime(2025, 5, 15, 11, 0)
        assert event.all_day is False
        assert event.location == "Here"
        assert event.description == "Desc"

    def test_defaults(self):
        cal = Calendar(calendar_id="c1", name="Cal")
        month = CalendarMonth(year=2025, month=5)
        event = CalendarEvent(
            id="e1",
            calendar=cal,
            month=month,
            title="Test",
            start_datetime=datetime.datetime(2025, 5, 15, 10, 0),
            end_datetime=datetime.datetime(2025, 5, 15, 11, 0),
        )
        assert event.all_day is False
        assert event.location is None
        assert event.description is None
