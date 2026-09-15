"""Slideshow photo index.

Tracks every original in the photos directory together with its processed
display variant and pixel dimensions. ``sync_photos`` is the single point
where the directory and the index are reconciled: new originals are
processed, missing ones are dropped along with their variants.

Playback order is a shuffle bag kept in process memory (see
:func:`next_photo`): every photo is shown once before any repeats, which the
old ``ORDER BY RANDOM()`` could not promise.
"""

from __future__ import annotations

import logging
import os
import random
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from . import ingest

logger = logging.getLogger(__name__)

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "slideshow.db")
PHOTOS_STATIC_REL_PATH = "photos"  # Relative path within the static folder

# How long a connection waits for a writer to release its lock before giving
# up. Uploads re-sync this database from a request thread while the slideshow
# reads it; without a busy timeout a reader that lands during a sync fails
# immediately with "database is locked".
BUSY_TIMEOUT_MS = 5000


def _apply_pragmas(conn) -> None:
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error as e:
        logger.warning("Could not apply SQLite pragmas: %s", e)


@contextmanager
def db_connection(commit: bool = True):
    """Yield a cursor and guarantee the connection is closed."""
    conn = sqlite3.connect(DATABASE_PATH)
    _apply_pragmas(conn)
    try:
        yield conn.cursor()
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create the table and add any columns older databases lack."""
    with db_connection() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS background_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL,
                processed TEXT,
                width INTEGER,
                height INTEGER
            )
            """)
        cursor.execute("PRAGMA table_info(background_photos)")
        existing = {row[1] for row in cursor.fetchall()}
        for column, ddl in (
            ("processed", "TEXT"),
            ("width", "INTEGER"),
            ("height", "INTEGER"),
        ):
            if column not in existing:
                cursor.execute(
                    f"ALTER TABLE background_photos ADD COLUMN {column} {ddl}"
                )
    logger.info("Slideshow database initialized.")


@dataclass(frozen=True)
class Photo:
    filename: str
    processed: Optional[str]
    width: Optional[int]
    height: Optional[int]

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        if self.width > self.height * 1.05:
            return "landscape"
        if self.height > self.width * 1.05:
            return "portrait"
        return "square"


def _photos_dir(static_folder_path: str) -> str:
    return os.path.join(static_folder_path, PHOTOS_STATIC_REL_PATH)


def _list_originals(photos_dir: str) -> set[str]:
    return {
        f
        for f in os.listdir(photos_dir)
        if os.path.isfile(os.path.join(photos_dir, f)) and ingest.is_original(f)
    }


def sync_photos(static_folder_path: str, max_dimension: Optional[int] = None) -> dict:
    """Reconcile the photos directory with the index.

    Returns counts of what happened. Best-effort: callers scan on startup,
    after uploads and periodically, and have nothing useful to do about a
    failure beyond logging it.
    """
    summary = {"added": 0, "processed": 0, "removed": 0, "failed": 0}
    photos_dir = _photos_dir(static_folder_path)
    if not os.path.isdir(photos_dir):
        logger.warning("Photos directory not found: %s", photos_dir)
        return summary

    if max_dimension is None:
        try:
            from src.config import get_config

            max_dimension = int(
                get_config().get(
                    "slideshow.max_dimension", ingest.DEFAULT_MAX_DIMENSION
                )
            )
        except Exception:
            max_dimension = ingest.DEFAULT_MAX_DIMENSION

    try:
        current_files = _list_originals(photos_dir)

        with db_connection() as cursor:
            cursor.execute("SELECT filename, processed FROM background_photos")
            rows = cursor.fetchall()
            db_files = {row[0] for row in rows}
            processed_by_file = {row[0]: row[1] for row in rows}

            files_to_remove = db_files - current_files
            if files_to_remove:
                logger.info("Removing %d photos from DB", len(files_to_remove))
                cursor.executemany(
                    "DELETE FROM background_photos WHERE filename = ?",
                    [(f,) for f in files_to_remove],
                )
                for f in files_to_remove:
                    ingest.remove_processed(f, photos_dir)
                summary["removed"] = len(files_to_remove)

            files_to_add = current_files - db_files
            if files_to_add:
                logger.info("Adding %d new photos to DB", len(files_to_add))
                cursor.executemany(
                    "INSERT OR IGNORE INTO background_photos (filename) VALUES (?)",
                    [(f,) for f in files_to_add],
                )
                summary["added"] = len(files_to_add)

        # Processing happens outside the transaction so a slow batch never
        # holds the write lock; each result is committed on its own.
        processed_dir = ingest.processed_dir(photos_dir)
        for filename in sorted(current_files):
            variant = processed_by_file.get(filename)
            if variant and os.path.isfile(os.path.join(processed_dir, variant)):
                continue
            result = ingest.process_photo(
                os.path.join(photos_dir, filename), photos_dir, max_dimension
            )
            if result is None:
                summary["failed"] += 1
                continue
            with db_connection() as cursor:
                cursor.execute(
                    "UPDATE background_photos SET processed = ?, width = ?, height = ? "
                    "WHERE filename = ?",
                    (result.filename, result.width, result.height, filename),
                )
            summary["processed"] += 1

        if any(summary.values()):
            _bag.invalidate()
        logger.info("Photo database sync complete: %s", summary)

    except Exception as e:
        logger.error("Error syncing photos: %s", e)

    return summary


def get_photo_count() -> int:
    """Number of photos with a display variant ready. 0 on any failure."""
    try:
        with db_connection(commit=False) as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM background_photos WHERE processed IS NOT NULL"
            )
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error("Error counting photos: %s", e)
        return 0


def get_ready_photos() -> list[Photo]:
    try:
        with db_connection(commit=False) as cursor:
            cursor.execute(
                "SELECT filename, processed, width, height FROM background_photos "
                "WHERE processed IS NOT NULL ORDER BY filename"
            )
            return [Photo(*row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Error listing photos: %s", e)
        return []


class _ShuffleBag:
    """Every photo once, in random order, then reshuffle."""

    def __init__(self):
        self._lock = threading.Lock()
        self._queue: list[Photo] = []
        self._valid = False
        self._last: Optional[str] = None

    def invalidate(self) -> None:
        with self._lock:
            self._valid = False

    def next(self) -> Optional[Photo]:
        with self._lock:
            if not self._valid or not self._queue:
                photos = get_ready_photos()
                if not photos:
                    self._valid = True
                    return None
                random.shuffle(photos)  # nosec B311 - not security-sensitive
                # Avoid showing the same photo twice in a row across a reshuffle.
                if len(photos) > 1 and photos[-1].filename == self._last:
                    photos[0], photos[-1] = photos[-1], photos[0]
                self._queue = photos
                self._valid = True
            photo = self._queue.pop()
            self._last = photo.filename
            return photo


_bag = _ShuffleBag()


def next_photo() -> Optional[Photo]:
    """The next photo to show, or None when there are none ready."""
    return _bag.next()


def get_random_photo_filename() -> Optional[str]:
    """Backwards-compatible helper: the *original* filename of the next photo."""
    photo = next_photo()
    return photo.filename if photo else None
