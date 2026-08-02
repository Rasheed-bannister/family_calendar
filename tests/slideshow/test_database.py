"""Tests for src/slideshow/database.py."""

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src.slideshow import database as slideshow_db


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary slideshow database."""
    db_path = str(tmp_path / "test_slideshow.db")
    with patch.object(slideshow_db, "DATABASE_PATH", db_path):
        slideshow_db.init_db()
        yield tmp_path, db_path


class _FailingCursor:
    """Cursor proxy whose statements always fail, simulating a disk error."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    def executemany(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")


class _TrackedConnection:
    """Proxy around a real sqlite3 connection that records whether it was closed."""

    def __init__(self, wrapped, failing_cursor=False):
        self._wrapped = wrapped
        self._failing_cursor = failing_cursor
        self.closed = False

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def cursor(self, *args, **kwargs):
        cursor = self._wrapped.cursor(*args, **kwargs)
        return _FailingCursor(cursor) if self._failing_cursor else cursor

    def close(self):
        self.closed = True
        self._wrapped.close()


@contextmanager
def track_connections(failing_cursor=False):
    """Wrap sqlite3.connect so tests can assert no connection is leaked.

    ``failing_cursor=True`` makes every statement issued through the cursor
    raise, which is the only way to make an ``IF NOT EXISTS`` schema statement
    fail mid-flight without depending on filesystem permissions.
    """
    opened = []
    real_connect = sqlite3.connect

    def fake_connect(*args, **kwargs):
        conn = _TrackedConnection(
            real_connect(*args, **kwargs), failing_cursor=failing_cursor
        )
        opened.append(conn)
        return conn

    with patch("src.slideshow.database.sqlite3.connect", fake_connect):
        yield opened


def _drop_photos_table(db_path):
    """Drop the table so the next operation against it raises mid-flight."""
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE background_photos")
    conn.commit()
    conn.close()


def _pragma(db_path, name):
    """Read a pragma over an independent connection."""
    conn = sqlite3.connect(db_path)
    value = conn.execute(f"PRAGMA {name}").fetchone()[0]
    conn.close()
    return value


class TestInitDb:
    """Tests for init_db."""

    def test_creates_table(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.init_db()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            conn.close()
            assert "background_photos" in tables


class TestSyncPhotos:
    """Tests for sync_photos."""

    def test_adds_new_photos(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        photos_dir.mkdir(parents=True)
        (photos_dir / "photo1.jpg").touch()
        (photos_dir / "photo2.png").touch()

        static_folder = str(tmp_path / "static")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(static_folder)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM background_photos")
            count = cursor.fetchone()[0]
            conn.close()
            assert count == 2

    def test_removes_deleted_photos(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        photos_dir.mkdir(parents=True)

        # Add a photo to DB manually
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO background_photos (filename) VALUES (?)", ("deleted.jpg",)
        )
        conn.commit()
        conn.close()

        static_folder = str(tmp_path / "static")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(static_folder)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM background_photos")
            count = cursor.fetchone()[0]
            conn.close()
            assert count == 0

    def test_ignores_non_image_files(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        photos_dir.mkdir(parents=True)
        (photos_dir / "readme.txt").touch()
        (photos_dir / "data.csv").touch()
        (photos_dir / "actual_photo.jpg").touch()

        static_folder = str(tmp_path / "static")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(static_folder)

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM background_photos")
            count = cursor.fetchone()[0]
            conn.close()
            assert count == 1

    def test_missing_photos_dir_no_error(self, temp_db):
        tmp_path, db_path = temp_db
        static_folder = str(tmp_path / "nonexistent_static")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(static_folder)  # Should not raise


class TestGetPhotoCount:
    """Tests for get_photo_count."""

    def test_count_empty(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_photo_count() == 0

    def test_count_with_photos(self, temp_db):
        _, db_path = temp_db
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO background_photos (filename) VALUES (?)", ("a.jpg",)
        )
        cursor.execute(
            "INSERT INTO background_photos (filename) VALUES (?)", ("b.png",)
        )
        conn.commit()
        conn.close()

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_photo_count() == 2


class TestGetRandomPhoto:
    """Tests for get_random_photo_filename."""

    def test_returns_photo_when_available(self, temp_db):
        tmp_path, db_path = temp_db
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO background_photos (filename) VALUES (?)", ("test.jpg",)
        )
        conn.commit()
        conn.close()

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            result = slideshow_db.get_random_photo_filename()
            assert result == "test.jpg"

    def test_returns_none_when_empty(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            result = slideshow_db.get_random_photo_filename()
            assert result is None


class TestConnectionLifecycle:
    """Every path must close its connection, including the failing ones.

    ``init_db`` had no try/finally at all: a statement that failed left the
    connection open for the lifetime of the process.
    """

    def test_init_db_does_not_leak_when_the_schema_statement_fails(self, tmp_path):
        db_path = str(tmp_path / "leaky.db")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections(failing_cursor=True) as opened:
                with pytest.raises(sqlite3.Error):
                    slideshow_db.init_db()

        assert opened, "expected init_db to open a connection"
        assert all(conn.closed for conn in opened)

    def test_get_photo_count_does_not_leak_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections() as opened:
                slideshow_db.get_photo_count()

        assert opened
        assert all(conn.closed for conn in opened)

    def test_get_random_photo_does_not_leak_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections() as opened:
                slideshow_db.get_random_photo_filename()

        assert opened
        assert all(conn.closed for conn in opened)

    def test_sync_photos_does_not_leak_on_error(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        photos_dir.mkdir(parents=True)
        (photos_dir / "photo1.jpg").touch()
        _drop_photos_table(db_path)

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections() as opened:
                slideshow_db.sync_photos(str(tmp_path / "static"))

        assert opened
        assert all(conn.closed for conn in opened)

    def test_failed_write_is_rolled_back(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with pytest.raises(sqlite3.Error):
                with slideshow_db.db_connection() as cursor:
                    cursor.execute(
                        "INSERT INTO background_photos (filename) VALUES ('half.jpg')"
                    )
                    cursor.execute("SELECT * FROM NoSuchTable")

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT filename FROM background_photos WHERE filename = 'half.jpg'"
        ).fetchone()
        conn.close()
        assert row is None


class TestBestEffortReads:
    """The read helpers keep swallowing errors; their callers cannot retry.

    They are the frontend's polling endpoints, so a transient failure degrades
    to "no photo yet" rather than an error page. The connection is still closed.
    """

    def test_get_photo_count_returns_zero_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_photo_count() == 0

    def test_get_random_photo_returns_none_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_random_photo_filename() is None

    def test_sync_photos_swallows_database_errors(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        photos_dir.mkdir(parents=True)
        (photos_dir / "photo1.jpg").touch()
        _drop_photos_table(db_path)

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"))  # must not raise


class TestPragmas:
    """WAL and a busy timeout: uploads write while the slideshow reads."""

    def test_wal_mode_enabled(self, temp_db):
        _, db_path = temp_db
        assert _pragma(db_path, "journal_mode") == "wal"

    def test_busy_timeout_applied(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with slideshow_db.db_connection(commit=False) as cursor:
                cursor.execute("PRAGMA busy_timeout")
                assert cursor.fetchone()[0] == slideshow_db.BUSY_TIMEOUT_MS

    def test_synchronous_is_normal(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with slideshow_db.db_connection(commit=False) as cursor:
                cursor.execute("PRAGMA synchronous")
                assert cursor.fetchone()[0] == 1  # NORMAL

    def test_committed_writes_are_visible_to_other_connections(self, temp_db):
        """WAL must not hide committed rows from the tests that read tmp DBs raw."""
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        photos_dir.mkdir(parents=True)
        (photos_dir / "visible.jpg").touch()

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"))

        conn = sqlite3.connect(db_path)
        rows = [
            row[0] for row in conn.execute("SELECT filename FROM background_photos")
        ]
        conn.close()
        assert rows == ["visible.jpg"]
