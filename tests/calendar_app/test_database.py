"""Tests for src/calendar_app/database.py."""

import datetime
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.calendar_app import database as db
from src.calendar_app.models import Calendar, CalendarEvent, CalendarMonth


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_calendar.db"
    with patch.object(db, "DATABASE_FILE", db_path):
        db.create_all()
        yield db_path


class TestCreateAll:
    """Tests for database creation."""

    def test_creates_tables(self, tmp_path):
        db_path = tmp_path / "test.db"
        with patch.object(db, "DATABASE_FILE", db_path):
            db.create_all()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in cursor.fetchall()}
            conn.close()
            assert "Calendar" in tables
            assert "CalendarMonth" in tables
            assert "CalendarEvent" in tables
            assert "DefaultColors" in tables
            assert "ColorIndex" in tables

    def test_populates_default_colors(self, tmp_path):
        db_path = tmp_path / "test.db"
        with patch.object(db, "DATABASE_FILE", db_path):
            db.create_all()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM DefaultColors")
            count = cursor.fetchone()[0]
            conn.close()
            assert count == len(db.DEFAULT_COLORS)

    def test_initializes_color_index(self, tmp_path):
        db_path = tmp_path / "test.db"
        with patch.object(db, "DATABASE_FILE", db_path):
            db.create_all()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT current_index FROM ColorIndex WHERE id = 1")
            index = cursor.fetchone()[0]
            conn.close()
            assert index == 0


class TestGetNextColor:
    """Tests for color rotation logic."""

    def test_returns_first_color(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            color = db.get_next_color(cursor)
            conn.commit()
            conn.close()
            assert color == db.DEFAULT_COLORS[0]

    def test_increments_index(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            db.get_next_color(cursor)
            cursor.execute("SELECT current_index FROM ColorIndex WHERE id = 1")
            index = cursor.fetchone()[0]
            conn.commit()
            conn.close()
            assert index == 1

    def test_wraps_around(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            # Set index to last color
            cursor.execute(
                "UPDATE ColorIndex SET current_index = ? WHERE id = 1",
                (len(db.DEFAULT_COLORS) - 1,),
            )
            db.get_next_color(cursor)  # Should get last color
            next_color = db.get_next_color(cursor)  # Should wrap to first
            conn.commit()
            conn.close()
            assert next_color == db.DEFAULT_COLORS[0]


class TestAddAndGetCalendar:
    """Tests for calendar CRUD operations."""

    def test_add_and_get_calendar(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            cal = Calendar(
                calendar_id="test-cal-1",
                name="Test Calendar",
                color_hex="#FF0000",
            )
            db.add_calendar(cal)
            result = db.get_calendar("test-cal-1")
            assert result is not None
            assert result.calendar_id == "test-cal-1"
            assert result.name == "Test Calendar"
            assert result.color == "#FF0000"

    def test_get_nonexistent_calendar(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            result = db.get_calendar("nonexistent")
            assert result is None

    def test_add_calendar_assigns_color_if_missing(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            cal = Calendar(
                calendar_id="no-color-cal",
                name="No Color",
                color_hex=None,
            )
            db.add_calendar(cal)
            result = db.get_calendar("no-color-cal")
            assert result is not None
            assert result.color is not None
            assert result.color == db.DEFAULT_COLORS[0]


class TestAddAndGetMonth:
    """Tests for month operations."""

    def test_add_and_get_month(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            month = CalendarMonth(year=2025, month=5)
            db.add_month(month)
            result = db.get_month("5.2025")
            assert result is not None
            assert result.year == 2025
            assert result.month == 5

    def test_get_nonexistent_month(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            result = db.get_month("99.9999")
            assert result is None


class TestAddAndGetEvents:
    """Tests for event operations."""

    def test_add_and_get_events(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            # Setup
            cal = Calendar(
                calendar_id="cal-1", name="Test Cal", color_hex="#FF0000"
            )
            db.add_calendar(cal)
            month = CalendarMonth(year=2025, month=5)
            db.add_month(month)

            event = CalendarEvent(
                id="evt-1",
                calendar=cal,
                month=month,
                title="Test Event",
                start_datetime=datetime.datetime(
                    2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
                ),
                end_datetime=datetime.datetime(
                    2025, 5, 15, 11, 0, 0, tzinfo=datetime.timezone.utc
                ),
                all_day=False,
                location="Here",
                description="Desc",
            )
            db.add_event(event)

            events = db.get_all_events(month)
            assert len(events) == 1
            assert events[0]["title"] == "Test Event"
            assert events[0]["calendar_name"] == "Test Cal"
            assert events[0]["calendar_color"] == "#FF0000"

    def test_get_events_for_month_range(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            cal = Calendar(
                calendar_id="cal-1", name="Test Cal", color_hex="#FF0000"
            )
            db.add_calendar(cal)
            month = CalendarMonth(year=2025, month=5)
            db.add_month(month)

            # Event in May
            event = CalendarEvent(
                id="evt-may",
                calendar=cal,
                month=month,
                title="May Event",
                start_datetime=datetime.datetime(
                    2025, 5, 15, 10, 0, 0, tzinfo=datetime.timezone.utc
                ),
                end_datetime=datetime.datetime(
                    2025, 5, 15, 11, 0, 0, tzinfo=datetime.timezone.utc
                ),
                all_day=False,
            )
            db.add_event(event)

            events = db.get_all_events_for_month_range(2025, 5)
            assert len(events) == 1
            assert events[0]["title"] == "May Event"


class TestRunMigrations:
    """Tests for database migrations."""

    def test_adds_display_name_column(self, tmp_path):
        """Test migration adds display_name to Calendar table."""
        db_path = tmp_path / "migrate_test.db"
        # Create DB without display_name column
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE Calendar (
                calendar_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT
            )
        """)
        conn.commit()
        conn.close()

        with patch.object(db, "DATABASE_FILE", db_path):
            db.run_migrations()

        # Verify column was added
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(Calendar)")
        columns = [col[1] for col in cursor.fetchall()]
        conn.close()
        assert "display_name" in columns

    def test_migration_idempotent(self, temp_db):
        """Running migrations on already-migrated DB should not error."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.run_migrations()  # Already has display_name from create_all
            db.run_migrations()  # Should not fail
