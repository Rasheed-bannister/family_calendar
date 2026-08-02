"""Tests for src/calendar_app/database.py."""

import datetime
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.calendar_app import database as db
from src.calendar_app.models import Calendar, CalendarEvent, CalendarMonth

NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_calendar.db"
    with patch.object(db, "DATABASE_FILE", db_path):
        db.create_all()
        yield db_path


@pytest.fixture
def local_tz():
    """Pin the app's display timezone so month bounds are deterministic."""
    with patch("src.config.get_local_timezone", return_value=NEW_YORK):
        yield NEW_YORK


class _TrackedConnection:
    """Proxy around a real sqlite3 connection that records whether it was closed."""

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def close(self):
        self.closed = True
        self._wrapped.close()


@contextmanager
def track_connections():
    """Wrap sqlite3.connect so tests can assert no connection is leaked."""
    opened = []
    real_connect = sqlite3.connect

    def fake_connect(*args, **kwargs):
        conn = _TrackedConnection(real_connect(*args, **kwargs))
        opened.append(conn)
        return conn

    with patch("src.calendar_app.database.sqlite3.connect", fake_connect):
        yield opened


def _drop_table(db_path, table):
    """Drop a table so the next operation against it raises mid-flight."""
    conn = sqlite3.connect(db_path)
    conn.execute(f"DROP TABLE {table}")
    conn.commit()
    conn.close()


def _pragma(db_path, name):
    """Read a pragma over an independent connection."""
    conn = sqlite3.connect(db_path)
    value = conn.execute(f"PRAGMA {name}").fetchone()[0]
    conn.close()
    return value


def _index_names(db_path):
    conn = sqlite3.connect(db_path)
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    conn.close()
    return names


def _insert_raw_event(db_path, event_id, start, end, month_id="8.2026", all_day=0):
    """Insert an event row with verbatim timestamp strings.

    Bypasses add_event on purpose so tests can reproduce the mixed-offset rows
    that real databases accumulated.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT OR REPLACE INTO CalendarEvent (
            id, calendar_id, month_id, title, start_datetime, end_datetime,
            all_day, location, description
        ) VALUES (?, 'cal-1', ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (event_id, month_id, event_id, start, end, all_day),
    )
    conn.commit()
    conn.close()


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
            cal = Calendar(calendar_id="cal-1", name="Test Cal", color_hex="#FF0000")
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
            cal = Calendar(calendar_id="cal-1", name="Test Cal", color_hex="#FF0000")
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


class TestMonthRangeIsLocalTime:
    """get_all_events_for_month_range must bound the month in local time.

    The bounds used to be hardcoded UTC strings compared lexicographically
    against rows stored with whatever offset Google returned, which is not an
    instant comparison at all.
    """

    @pytest.fixture(autouse=True)
    def _calendar(self, temp_db, local_tz):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_calendar(
                Calendar(calendar_id="cal-1", name="Test Cal", color_hex="#FF0000")
            )
        self.db_path = temp_db

    def _titles_for(self, year, month):
        with patch.object(db, "DATABASE_FILE", self.db_path):
            return {e["title"] for e in db.get_all_events_for_month_range(year, month)}

    def test_late_evening_event_on_last_day_is_in_that_month(self):
        """22:00 on Aug 31 in New York is 02:00 Sep 1 UTC - still August."""
        _insert_raw_event(
            self.db_path,
            "late-aug-31",
            "2026-08-31T22:00:00-04:00",
            "2026-08-31T23:00:00-04:00",
        )
        assert "late-aug-31" in self._titles_for(2026, 8)

    def test_late_evening_event_on_last_day_is_not_in_the_next_month(self):
        _insert_raw_event(
            self.db_path,
            "late-aug-31",
            "2026-08-31T22:00:00-04:00",
            "2026-08-31T23:00:00-04:00",
        )
        assert "late-aug-31" not in self._titles_for(2026, 9)

    def test_previous_month_evening_event_is_excluded(self):
        """A UTC window pulled in the tail of the previous local month."""
        _insert_raw_event(
            self.db_path,
            "late-jul-31",
            "2026-07-31T22:00:00-04:00",
            "2026-07-31T23:00:00-04:00",
            month_id="7.2026",
        )
        assert "late-jul-31" not in self._titles_for(2026, 8)
        assert "late-jul-31" in self._titles_for(2026, 7)

    def test_first_moment_of_local_month_is_included(self):
        _insert_raw_event(
            self.db_path,
            "midnight-aug-1",
            "2026-08-01T00:00:00-04:00",
            "2026-08-01T01:00:00-04:00",
        )
        assert "midnight-aug-1" in self._titles_for(2026, 8)

    def test_mixed_offset_rows_are_compared_as_instants(self):
        """Rows written with different offsets must still sort/filter correctly."""
        _insert_raw_event(
            self.db_path,
            "stored-utc",
            "2026-08-15T18:00:00+00:00",
            "2026-08-15T19:00:00+00:00",
        )
        _insert_raw_event(
            self.db_path,
            "stored-eastern",
            "2026-08-15T09:00:00-04:00",
            "2026-08-15T10:00:00-04:00",
        )
        _insert_raw_event(
            self.db_path,
            "stored-naive",
            "2026-08-15T12:00:00",
            "2026-08-15T13:00:00",
        )

        with patch.object(db, "DATABASE_FILE", self.db_path):
            events = db.get_all_events_for_month_range(2026, 8)

        # Instants are 12:00Z (naive), 13:00Z (-04:00) and 18:00Z. Sorting the
        # raw strings would have put "...T09:00:00-04:00" first.
        assert [e["title"] for e in events] == [
            "stored-naive",
            "stored-eastern",
            "stored-utc",
        ]

    def test_all_day_event_on_first_of_month_is_included(self):
        """All-day events are stored as floating midnight-UTC dates."""
        _insert_raw_event(
            self.db_path,
            "all-day-aug-1",
            "2026-08-01T00:00:00+00:00",
            "2026-08-02T00:00:00+00:00",
            all_day=1,
        )
        assert "all-day-aug-1" in self._titles_for(2026, 8)

    def test_all_day_event_on_last_of_month_is_included(self):
        _insert_raw_event(
            self.db_path,
            "all-day-aug-31",
            "2026-08-31T00:00:00+00:00",
            "2026-09-01T00:00:00+00:00",
            all_day=1,
        )
        assert "all-day-aug-31" in self._titles_for(2026, 8)

    def test_event_spanning_whole_month_is_included(self):
        _insert_raw_event(
            self.db_path,
            "spanning",
            "2026-07-20T10:00:00-04:00",
            "2026-09-05T10:00:00-04:00",
            month_id="7.2026",
        )
        assert "spanning" in self._titles_for(2026, 8)

    def test_december_window_rolls_over_year_boundary(self):
        _insert_raw_event(
            self.db_path,
            "new-years-eve",
            "2026-12-31T22:00:00-05:00",
            "2026-12-31T23:30:00-05:00",
            month_id="12.2026",
        )
        assert "new-years-eve" in self._titles_for(2026, 12)
        assert "new-years-eve" not in self._titles_for(2027, 1)


class TestSerializeDatetime:
    """Stored timestamps stay offset-qualified and keep their local offset."""

    def test_preserves_offset_rather_than_converting_to_utc(self):
        value = datetime.datetime(2026, 8, 31, 22, 0, tzinfo=NEW_YORK)
        assert db.serialize_datetime(value) == "2026-08-31T22:00:00-04:00"

    def test_naive_value_is_stamped_as_utc(self):
        value = datetime.datetime(2026, 8, 31, 22, 0)
        assert db.serialize_datetime(value) == "2026-08-31T22:00:00+00:00"

    def test_round_trips_through_fromisoformat(self):
        """The view layer reads rows back with fromisoformat."""
        value = datetime.datetime(2026, 8, 31, 22, 0, tzinfo=NEW_YORK)
        parsed = datetime.datetime.fromisoformat(db.serialize_datetime(value))
        assert parsed == value
        # Day placement in the calendar grid depends on this staying local.
        assert parsed.date() == datetime.date(2026, 8, 31)

    def test_add_event_stores_local_offset(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            cal = Calendar(calendar_id="cal-1", name="Test Cal", color_hex="#FF0000")
            db.add_calendar(cal)
            month = CalendarMonth(year=2026, month=8)
            db.add_month(month)
            db.add_event(
                CalendarEvent(
                    id="evt-late",
                    calendar=cal,
                    month=month,
                    title="Late",
                    start_datetime=datetime.datetime(
                        2026, 8, 31, 22, 0, tzinfo=NEW_YORK
                    ),
                    end_datetime=datetime.datetime(2026, 8, 31, 23, 0, tzinfo=NEW_YORK),
                    all_day=False,
                )
            )

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT start_datetime FROM CalendarEvent WHERE id = 'evt-late'"
        ).fetchone()
        conn.close()
        assert row[0] == "2026-08-31T22:00:00-04:00"


class TestCheckEventExistsRemoved:
    """BUG 16: dead helper with a row-index bug, deleted rather than fixed."""

    def test_helper_is_gone(self):
        assert not hasattr(db, "check_event_exists")


class TestRunMigrations:
    """Tests for database migrations."""

    def test_adds_display_name_column(self, tmp_path):
        """Test migration adds display_name to Calendar table."""
        db_path = tmp_path / "migrate_test.db"
        # Create DB without display_name column
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE Calendar (
                calendar_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT
            )
        """
        )
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

    def test_leaves_existing_mixed_offset_rows_alone(self, temp_db):
        """Pre-existing rows are already comparable; do not rewrite them."""
        _insert_raw_event(
            temp_db,
            "legacy",
            "2026-08-31T22:00:00-04:00",
            "2026-08-31T23:00:00-04:00",
        )
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.run_migrations()

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT start_datetime, end_datetime FROM CalendarEvent WHERE id = 'legacy'"
        ).fetchone()
        conn.close()
        assert row == ("2026-08-31T22:00:00-04:00", "2026-08-31T23:00:00-04:00")

    def test_repairs_timestamps_sqlite_cannot_parse(self, temp_db):
        """A row SQLite can't read would silently vanish from the month view."""
        _insert_raw_event(
            temp_db,
            "odd-format",
            "2026-08-15T10:00:00+00:00:00",
            "2026-08-15T11:00:00+00:00:00",
        )
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.run_migrations()

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT start_datetime FROM CalendarEvent WHERE id = 'odd-format'"
        ).fetchone()
        parsed = conn.execute("SELECT datetime(?)", (row[0],)).fetchone()
        conn.close()
        assert parsed[0] is not None

    def test_unrecoverable_row_is_kept_not_dropped(self, temp_db):
        """Never silently delete data we cannot interpret."""
        _insert_raw_event(temp_db, "garbage", "not-a-timestamp", "also-garbage")
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.run_migrations()

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT start_datetime, end_datetime FROM CalendarEvent WHERE id = 'garbage'"
        ).fetchone()
        conn.close()
        assert row == ("not-a-timestamp", "also-garbage")


def _raising_step(cursor):
    """A migration step that always fails, for step-isolation tests."""
    raise sqlite3.OperationalError("boom")


@db.db_connection
def _count_calendars(cursor):
    """Decorator user standing in for the ones in src/calendar_app/utils.py."""
    cursor.execute("SELECT COUNT(*) FROM Calendar")
    return cursor.fetchone()[0]


@db.db_connection
def _insert_then_fail(cursor):
    """Writes a row and then blows up, to prove the transaction is rolled back."""
    cursor.execute(
        "INSERT INTO Calendar (calendar_id, name, color) VALUES ('half-written', 'x', '#000')"
    )
    cursor.execute("SELECT * FROM NoSuchTable")


class TestErrorContract:
    """A database failure must not be reported as an empty result.

    The old decorator logged every ``sqlite3.Error`` and returned ``[]`` from
    whichever function raised it. ``get_calendar`` therefore answered "no such
    calendar" when the database was unreachable, and
    ``create_calendar_events_from_google_data`` - which branches on
    ``if not calendar_obj`` - created a duplicate calendar in response.
    """

    def test_get_calendar_raises_instead_of_returning_a_falsy_value(self, temp_db):
        _drop_table(temp_db, "Calendar")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.get_calendar("cal-1")

    def test_get_calendar_returns_none_only_when_the_row_is_missing(self, temp_db):
        """The other half of the contract: absence still reads as None."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            assert db.get_calendar("never-stored") is None

    def test_get_month_raises_on_database_error(self, temp_db):
        _drop_table(temp_db, "CalendarMonth")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.get_month("5.2025")

    def test_add_month_raises_on_database_error(self, temp_db):
        _drop_table(temp_db, "CalendarMonth")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.add_month(CalendarMonth(year=2025, month=5))

    def test_add_calendar_raises_on_database_error(self, temp_db):
        _drop_table(temp_db, "Calendar")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.add_calendar(Calendar(calendar_id="c", name="n", color_hex="#fff"))

    def test_add_event_raises_on_database_error(self, temp_db):
        _drop_table(temp_db, "CalendarEvent")
        cal = Calendar(calendar_id="cal-1", name="Test Cal", color_hex="#FF0000")
        month = CalendarMonth(year=2025, month=5)
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.add_event(
                    CalendarEvent(
                        id="evt-1",
                        calendar=cal,
                        month=month,
                        title="T",
                        start_datetime=datetime.datetime(
                            2025, 5, 15, 10, 0, tzinfo=datetime.timezone.utc
                        ),
                        end_datetime=datetime.datetime(
                            2025, 5, 15, 11, 0, tzinfo=datetime.timezone.utc
                        ),
                        all_day=False,
                    )
                )

    def test_get_all_events_raises_instead_of_returning_an_empty_list(self, temp_db):
        _drop_table(temp_db, "CalendarEvent")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.get_all_events(CalendarMonth(year=2025, month=5))

    def test_get_all_events_for_month_range_raises_on_database_error(
        self, temp_db, local_tz
    ):
        _drop_table(temp_db, "CalendarEvent")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                db.get_all_events_for_month_range(2025, 5)

    def test_decorated_function_propagates_database_error(self, temp_db):
        """utils.py's @db_connection users get the same contract."""
        _drop_table(temp_db, "Calendar")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                _count_calendars()


class TestDecoratorCompatibility:
    """src/calendar_app/utils.py applies @db_connection to its own functions."""

    def test_decorator_injects_cursor_and_returns_value(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_calendar(Calendar(calendar_id="c1", name="One", color_hex="#fff"))
            assert _count_calendars() == 1

    def test_decorator_commits_on_success(self, temp_db):
        @db.db_connection
        def insert(cursor):
            cursor.execute(
                "INSERT INTO Calendar (calendar_id, name, color) VALUES (?, ?, ?)",
                ("committed", "Committed", "#fff"),
            )

        with patch.object(db, "DATABASE_FILE", temp_db):
            insert()

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT name FROM Calendar WHERE calendar_id = 'committed'"
        ).fetchone()
        conn.close()
        assert row == ("Committed",)

    def test_get_next_color_accepts_cursor_as_keyword(self, temp_db):
        """utils.add_events calls get_next_color(cursor=cursor)."""
        conn = sqlite3.connect(temp_db)
        color = db.get_next_color(cursor=conn.cursor())
        conn.commit()
        conn.close()
        assert color == db.DEFAULT_COLORS[0]


class TestConnectionLifecycle:
    """Connections must be closed and transactions rolled back on failure."""

    def test_connection_closed_when_a_read_fails(self, temp_db):
        _drop_table(temp_db, "Calendar")
        with patch.object(db, "DATABASE_FILE", temp_db):
            with track_connections() as opened:
                with pytest.raises(sqlite3.Error):
                    db.get_calendar("cal-1")

        assert opened, "expected the operation to open a connection"
        assert all(conn.closed for conn in opened)

    def test_connection_closed_when_a_decorated_function_raises(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            with track_connections() as opened:
                with pytest.raises(sqlite3.Error):
                    _insert_then_fail()

        assert opened
        assert all(conn.closed for conn in opened)

    def test_failed_write_is_rolled_back(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            with pytest.raises(sqlite3.Error):
                _insert_then_fail()

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT calendar_id FROM Calendar WHERE calendar_id = 'half-written'"
        ).fetchone()
        conn.close()
        assert row is None


class TestCreateAllIsNonDestructive:
    """create_all used to open DATABASE_FILE with mode "w" before connecting."""

    def test_does_not_truncate_an_existing_database(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_calendar(
                Calendar(calendar_id="keep-1", name="Keep", color_hex="#f0f")
            )

            db.create_all()

            survivor = db.get_calendar("keep-1")

        assert survivor is not None
        assert survivor.name == "Keep"

    def test_is_idempotent(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.create_all()
            db.create_all()

        conn = sqlite3.connect(temp_db)
        count = conn.execute("SELECT COUNT(*) FROM DefaultColors").fetchone()[0]
        conn.close()
        assert count == len(db.DEFAULT_COLORS)


class TestPragmas:
    """WAL and a busy timeout, for a background writer on an SD card."""

    def test_wal_mode_enabled(self, temp_db):
        assert _pragma(temp_db, "journal_mode") == "wal"

    def test_busy_timeout_applied(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            with db.db_connection(commit=False) as cursor:
                cursor.execute("PRAGMA busy_timeout")
                assert cursor.fetchone()[0] == db.BUSY_TIMEOUT_MS

    def test_synchronous_is_normal(self, temp_db):
        with patch.object(db, "DATABASE_FILE", temp_db):
            with db.db_connection(commit=False) as cursor:
                cursor.execute("PRAGMA synchronous")
                assert cursor.fetchone()[0] == 1  # NORMAL

    def test_committed_writes_are_visible_to_other_connections(self, temp_db):
        """WAL must not hide committed rows from the tests that read tmp DBs raw."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            db.add_calendar(Calendar(calendar_id="visible", name="V", color_hex="#fff"))

        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT name FROM Calendar WHERE calendar_id = 'visible'"
        ).fetchone()
        conn.close()
        assert row == ("V",)

    def test_foreign_key_enforcement_stays_off(self, temp_db):
        """get_all_events LEFT JOINs Calendar because orphaned events exist."""
        with patch.object(db, "DATABASE_FILE", temp_db):
            with db.db_connection(commit=False) as cursor:
                cursor.execute("PRAGMA foreign_keys")
                assert cursor.fetchone()[0] == 0


class TestIndexes:
    """Indexes exist for the columns the queries actually filter and sort on."""

    def test_create_all_creates_indexes(self, temp_db):
        names = _index_names(temp_db)
        assert "idx_calendarevent_month_id" in names
        assert "idx_calendarevent_start_datetime" in names

    def test_run_migrations_adds_indexes_to_an_existing_database(self, temp_db):
        """Databases that predate the indexes must pick them up too."""
        conn = sqlite3.connect(temp_db)
        conn.execute("DROP INDEX idx_calendarevent_month_id")
        conn.execute("DROP INDEX idx_calendarevent_start_datetime")
        conn.commit()
        conn.close()

        with patch.object(db, "DATABASE_FILE", temp_db):
            db.run_migrations()

        names = _index_names(temp_db)
        assert "idx_calendarevent_month_id" in names
        assert "idx_calendarevent_start_datetime" in names

    def test_month_id_lookup_uses_index(self, temp_db):
        """cleanup_deleted_events and get_all_events filter on month_id."""
        conn = sqlite3.connect(temp_db)
        plan = " ".join(
            str(row)
            for row in conn.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM CalendarEvent WHERE month_id = ?",
                ("8.2026",),
            )
        )
        conn.close()
        assert "idx_calendarevent_month_id" in plan

    def test_month_range_query_uses_index_and_avoids_a_sort(self, temp_db):
        """get_all_events_for_month_range filters and orders by datetime(start)."""
        conn = sqlite3.connect(temp_db)
        plan = " ".join(
            str(row)
            for row in conn.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT ev.id
                FROM CalendarEvent ev
                LEFT JOIN Calendar cal ON ev.calendar_id = cal.calendar_id
                WHERE
                    datetime(ev.start_datetime) <= datetime(?)
                    AND datetime(ev.end_datetime) >= datetime(?)
                ORDER BY datetime(ev.start_datetime)
                """,
                ("2026-09-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00"),
            )
        )
        conn.close()
        assert "idx_calendarevent_start_datetime" in plan
        assert "TEMP B-TREE" not in plan.upper()


class TestRunMigrationsErrorHandling:
    """A failed migration must not take app startup down with it."""

    def test_database_error_does_not_propagate(self, tmp_path):
        db_path = tmp_path / "unreachable.db"
        with patch.object(db, "DATABASE_FILE", db_path):
            with patch(
                "src.calendar_app.database.sqlite3.connect",
                side_effect=sqlite3.OperationalError("unable to open database file"),
            ):
                db.run_migrations()  # must not raise

    def test_earlier_step_survives_a_later_failure(self, tmp_path):
        """Steps commit independently, so one failure cannot undo the others."""
        db_path = tmp_path / "migrate_steps.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE Calendar (
                calendar_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT
            )
            """
        )
        conn.commit()
        conn.close()

        with patch.object(db, "DATABASE_FILE", db_path):
            with patch.object(db, "_create_indexes", _raising_step):
                db.run_migrations()

        conn = sqlite3.connect(db_path)
        columns = [col[1] for col in conn.execute("PRAGMA table_info(Calendar)")]
        conn.close()
        assert "display_name" in columns
