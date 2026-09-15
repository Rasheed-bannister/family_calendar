"""Tests for src/slideshow/database.py.

Real SQLite files under tmp_path and real (tiny) images made with Pillow,
so ``sync_photos`` exercises the ingest pipeline end to end.
"""

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from PIL import Image

from src.slideshow import database as slideshow_db


@pytest.fixture(autouse=True)
def reset_shuffle_bag():
    slideshow_db._bag.invalidate()
    yield
    slideshow_db._bag.invalidate()


@pytest.fixture
def temp_db(tmp_path):
    """A fresh slideshow database plus an empty static/photos tree."""
    db_path = str(tmp_path / "test_slideshow.db")
    (tmp_path / "static" / "photos").mkdir(parents=True)
    with patch.object(slideshow_db, "DATABASE_PATH", db_path):
        slideshow_db.init_db()
        yield tmp_path, db_path


def make_image(path, size=(40, 20), orientation=None):
    img = Image.new("RGB", size, color=(10, 200, 30))
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif.tobytes()
    img.save(path, **kwargs)
    return path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT filename, processed, width, height FROM background_photos ORDER BY filename"
    ).fetchall()
    conn.close()
    return rows


class _FailingCursor:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    def executemany(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")


class _TrackedConnection:
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
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE background_photos")
    conn.commit()
    conn.close()


def _pragma(db_path, name):
    conn = sqlite3.connect(db_path)
    value = conn.execute(f"PRAGMA {name}").fetchone()[0]
    conn.close()
    return value


class TestInitDb:
    def test_creates_table_with_variant_columns(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.init_db()
        conn = sqlite3.connect(db_path)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(background_photos)")
        }
        conn.close()
        assert {"id", "filename", "processed", "width", "height"} <= columns

    def test_migrates_an_old_database(self, tmp_path):
        """Databases from before the overhaul only had id + filename."""
        db_path = str(tmp_path / "old.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE background_photos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "filename TEXT UNIQUE NOT NULL)"
        )
        conn.execute("INSERT INTO background_photos (filename) VALUES ('keep.jpg')")
        conn.commit()
        conn.close()

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.init_db()
            slideshow_db.init_db()  # idempotent

        assert _rows(db_path) == [("keep.jpg", None, None, None)]


class TestSyncPhotos:
    def test_indexes_and_processes_new_originals(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        make_image(photos_dir / "photo1.jpg", size=(40, 20))
        make_image(photos_dir / "photo2.png", size=(20, 40))

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            summary = slideshow_db.sync_photos(
                str(tmp_path / "static"), max_dimension=2048
            )

        assert summary == {"added": 2, "processed": 2, "removed": 0, "failed": 0}
        assert _rows(db_path) == [
            ("photo1.jpg", "photo1.jpg", 40, 20),
            ("photo2.png", "photo2.jpg", 20, 40),
        ]
        processed = photos_dir / "processed"
        assert sorted(p.name for p in processed.iterdir()) == [
            "photo1.jpg",
            "photo2.jpg",
        ]

    def test_exif_orientation_is_applied_during_ingest(self, temp_db):
        tmp_path, db_path = temp_db
        make_image(
            tmp_path / "static" / "photos" / "rot.jpg", size=(40, 20), orientation=6
        )
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
        assert _rows(db_path) == [("rot.jpg", "rot.jpg", 20, 40)]

    def test_uses_configured_max_dimension(self, temp_db):
        tmp_path, db_path = temp_db
        make_image(tmp_path / "static" / "photos" / "big.jpg", size=(200, 100))

        class Cfg:
            def get(self, key, default=None):
                return {"slideshow.max_dimension": 50}.get(key, default)

        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with patch("src.config.get_config", return_value=Cfg()):
                slideshow_db.sync_photos(str(tmp_path / "static"))
        assert _rows(db_path) == [("big.jpg", "big.jpg", 50, 25)]

    def test_second_sync_is_a_noop(self, temp_db):
        tmp_path, db_path = temp_db
        make_image(tmp_path / "static" / "photos" / "photo1.jpg")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
            summary = slideshow_db.sync_photos(
                str(tmp_path / "static"), max_dimension=2048
            )
        assert summary == {"added": 0, "processed": 0, "removed": 0, "failed": 0}

    def test_missing_variant_is_regenerated(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        make_image(photos_dir / "photo1.jpg")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
            (photos_dir / "processed" / "photo1.jpg").unlink()
            summary = slideshow_db.sync_photos(
                str(tmp_path / "static"), max_dimension=2048
            )
        assert summary["processed"] == 1
        assert (photos_dir / "processed" / "photo1.jpg").exists()

    def test_removes_deleted_photos_and_their_variants(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        original = make_image(photos_dir / "deleted.jpg")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
            assert (photos_dir / "processed" / "deleted.jpg").exists()
            original.unlink()
            summary = slideshow_db.sync_photos(
                str(tmp_path / "static"), max_dimension=2048
            )
        assert summary["removed"] == 1
        assert _rows(db_path) == []
        assert not (photos_dir / "processed" / "deleted.jpg").exists()

    def test_ignores_non_image_files_and_subdirectories(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        (photos_dir / "readme.txt").touch()
        (photos_dir / "thumbnails").mkdir()
        make_image(photos_dir / "thumbnails" / "x_thumb.jpg")
        make_image(photos_dir / "actual_photo.jpg")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
        assert [r[0] for r in _rows(db_path)] == ["actual_photo.jpg"]

    def test_unreadable_original_is_indexed_but_not_ready(self, temp_db):
        tmp_path, db_path = temp_db
        (tmp_path / "static" / "photos" / "broken.jpg").write_bytes(b"nope")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            summary = slideshow_db.sync_photos(
                str(tmp_path / "static"), max_dimension=2048
            )
            assert slideshow_db.get_photo_count() == 0
        assert summary["failed"] == 1
        assert _rows(db_path) == [("broken.jpg", None, None, None)]

    def test_missing_photos_dir_no_error(self, temp_db):
        tmp_path, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            summary = slideshow_db.sync_photos(str(tmp_path / "nonexistent"))
        assert summary == {"added": 0, "processed": 0, "removed": 0, "failed": 0}

    def test_sync_refreshes_the_shuffle_bag(self, temp_db):
        tmp_path, db_path = temp_db
        photos_dir = tmp_path / "static" / "photos"
        make_image(photos_dir / "a.jpg")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
            assert slideshow_db.next_photo().filename == "a.jpg"
            make_image(photos_dir / "b.jpg")
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
            seen = {slideshow_db.next_photo().filename for _ in range(2)}
        assert seen == {"a.jpg", "b.jpg"}


class TestPhotoCountAndListing:
    def test_count_empty(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_photo_count() == 0

    def test_count_only_ready_photos(self, temp_db):
        _, db_path = temp_db
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO background_photos (filename, processed, width, height) "
            "VALUES ('a.jpg', 'a.jpg', 10, 10)"
        )
        conn.execute("INSERT INTO background_photos (filename) VALUES ('pending.png')")
        conn.commit()
        conn.close()
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_photo_count() == 1
            ready = slideshow_db.get_ready_photos()
        assert [p.filename for p in ready] == ["a.jpg"]
        assert ready[0].orientation == "square"

    @pytest.mark.parametrize(
        "w,h,expected",
        [
            (40, 20, "landscape"),
            (20, 40, "portrait"),
            (30, 30, "square"),
            (None, 30, "unknown"),
        ],
    )
    def test_orientation(self, w, h, expected):
        assert slideshow_db.Photo("f", "f", w, h).orientation == expected


def _seed_ready(db_path, names):
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO background_photos (filename, processed, width, height) VALUES (?, ?, 10, 10)",
        [(n, n) for n in names],
    )
    conn.commit()
    conn.close()


class TestNextPhoto:
    """A shuffle bag: every photo once before any repeats."""

    def test_returns_none_when_empty(self, temp_db):
        _, db_path = temp_db
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.next_photo() is None
            assert slideshow_db.get_random_photo_filename() is None

    def test_every_photo_once_per_cycle(self, temp_db):
        _, db_path = temp_db
        names = [f"p{i}.jpg" for i in range(6)]
        _seed_ready(db_path, names)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            first_cycle = [slideshow_db.next_photo().filename for _ in names]
            second_cycle = [slideshow_db.next_photo().filename for _ in names]
        assert sorted(first_cycle) == names
        assert sorted(second_cycle) == names

    def test_no_immediate_repeat_across_reshuffle(self, temp_db):
        _, db_path = temp_db
        _seed_ready(db_path, ["a.jpg", "b.jpg", "c.jpg"])
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            for _ in range(20):
                sequence = [slideshow_db.next_photo().filename for _ in range(6)]
                for previous, current in zip(sequence, sequence[1:]):
                    assert previous != current

    def test_compat_helper_returns_original_filename(self, temp_db):
        _, db_path = temp_db
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO background_photos (filename, processed, width, height) "
            "VALUES ('IMG.HEIC', 'IMG.jpg', 10, 10)"
        )
        conn.commit()
        conn.close()
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_random_photo_filename() == "IMG.HEIC"

    def test_pending_photos_are_never_served(self, temp_db):
        _, db_path = temp_db
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO background_photos (filename) VALUES ('pending.jpg')")
        conn.commit()
        conn.close()
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.next_photo() is None


class TestConnectionLifecycle:
    def test_init_db_does_not_leak_when_the_schema_statement_fails(self, tmp_path):
        db_path = str(tmp_path / "leaky.db")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections(failing_cursor=True) as opened:
                with pytest.raises(sqlite3.Error):
                    slideshow_db.init_db()
        assert opened
        assert all(conn.closed for conn in opened)

    def test_get_photo_count_does_not_leak_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections() as opened:
                slideshow_db.get_photo_count()
        assert opened
        assert all(conn.closed for conn in opened)

    def test_next_photo_does_not_leak_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            with track_connections() as opened:
                assert slideshow_db.next_photo() is None
        assert opened
        assert all(conn.closed for conn in opened)

    def test_sync_photos_does_not_leak_on_error(self, temp_db):
        tmp_path, db_path = temp_db
        make_image(tmp_path / "static" / "photos" / "photo1.jpg")
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
        assert _rows(db_path) == []


class TestBestEffortReads:
    def test_get_photo_count_returns_zero_on_error(self, temp_db):
        _, db_path = temp_db
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            assert slideshow_db.get_photo_count() == 0

    def test_sync_photos_swallows_database_errors(self, temp_db):
        tmp_path, db_path = temp_db
        make_image(tmp_path / "static" / "photos" / "photo1.jpg")
        _drop_photos_table(db_path)
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"))  # must not raise


class TestPragmas:
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
        tmp_path, db_path = temp_db
        make_image(tmp_path / "static" / "photos" / "visible.jpg")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.sync_photos(str(tmp_path / "static"), max_dimension=2048)
        assert [r[0] for r in _rows(db_path)] == ["visible.jpg"]
