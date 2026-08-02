import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "slideshow.db")
PHOTOS_STATIC_REL_PATH = "photos"  # Relative path within the static folder

# How long a connection waits for a writer to release its lock before giving up.
# Photo uploads re-sync this database from a request thread while the slideshow
# polls it for the next image; without a busy timeout a reader that lands during
# a sync fails immediately with "database is locked".
BUSY_TIMEOUT_MS = 5000


def _apply_pragmas(conn) -> None:
    """Put a fresh connection into the mode this app needs.

    WAL lets the slideshow keep reading while an upload re-syncs the photo list,
    instead of the two blocking each other; the setting lives in the database
    header, so this is a no-op after the first connection. ``synchronous=NORMAL``
    is the standard companion to WAL and spares an SD card an fsync per commit.

    A pragma that cannot be applied is logged and ignored - the database still
    works, just less happily under concurrency.
    """
    try:
        # Set the busy timeout first so the journal_mode switch itself waits for
        # a concurrent writer rather than failing.
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error as e:
        logger.warning("Could not apply SQLite pragmas: %s", e)


@contextmanager
def db_connection(commit: bool = True):
    """
    Yields a cursor for DATABASE_PATH and guarantees the connection is closed.

    On success the transaction is committed (unless ``commit=False``); on any
    exception it is rolled back and the exception is re-raised so callers can
    tell a failure apart from an empty result. The connection is closed in a
    ``finally`` block either way, so a locked database or a disk error cannot
    leak file descriptors on a long-running process.
    """
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
    """Initializes the slideshow database and creates the table if it doesn't exist."""
    with db_connection() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS background_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE NOT NULL
            )
        """)
    logger.info("Slideshow database initialized.")


def sync_photos(static_folder_path):
    """Scans the photos directory and updates the database."""
    photos_dir = os.path.join(static_folder_path, PHOTOS_STATIC_REL_PATH)
    if not os.path.isdir(photos_dir):
        logger.warning("Photos directory not found: %s", photos_dir)
        return

    try:
        # Get current files in the directory
        valid_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        current_files = {
            f
            for f in os.listdir(photos_dir)
            if os.path.isfile(os.path.join(photos_dir, f))
            and f.lower().endswith(valid_extensions)
        }

        with db_connection() as cursor:
            # Get files currently in the database
            cursor.execute("SELECT filename FROM background_photos")
            db_files = {row[0] for row in cursor.fetchall()}

            # Add new files
            files_to_add = current_files - db_files
            if files_to_add:
                logger.info("Adding %d new photos to DB", len(files_to_add))
                cursor.executemany(
                    "INSERT OR IGNORE INTO background_photos (filename) VALUES (?)",
                    [(f,) for f in files_to_add],
                )

            # Remove files no longer present
            files_to_remove = db_files - current_files
            if files_to_remove:
                logger.info("Removing %d photos from DB", len(files_to_remove))
                cursor.executemany(
                    "DELETE FROM background_photos WHERE filename = ?",
                    [(f,) for f in files_to_remove],
                )

        logger.info("Photo database sync complete.")

    except Exception as e:
        # Callers sync opportunistically (on page load, after an upload) and have
        # nothing useful to do about a failure, so this stays best-effort.
        logger.error("Error syncing photos: %s", e)


def get_photo_count():
    """Returns the number of photos in the database.

    Returns 0 if the count cannot be read; the caller only uses this to decide
    whether to tell the frontend "no photos yet", and a failure there is not
    worth breaking the page over.
    """
    try:
        with db_connection(commit=False) as cursor:
            cursor.execute("SELECT COUNT(*) FROM background_photos")
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error("Error counting photos: %s", e)
        return 0


def get_random_photo_filename():
    """Fetches a random photo filename from the database, or None if there is none."""
    try:
        with db_connection(commit=False) as cursor:
            cursor.execute(
                "SELECT filename FROM background_photos ORDER BY RANDOM() LIMIT 1"
            )
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error("Error fetching random photo: %s", e)
        return None
