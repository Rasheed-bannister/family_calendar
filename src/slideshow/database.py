import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "slideshow.db")
PHOTOS_STATIC_REL_PATH = "photos"  # Relative path within the static folder


def init_db():
    """Initializes the slideshow database and creates the table if it doesn't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS background_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Slideshow database initialized.")


def sync_photos(static_folder_path):
    """Scans the photos directory and updates the database."""
    photos_dir = os.path.join(static_folder_path, PHOTOS_STATIC_REL_PATH)
    if not os.path.isdir(photos_dir):
        logger.warning("Photos directory not found: %s", photos_dir)
        return

    conn = None
    try:
        # Get current files in the directory
        valid_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        current_files = {
            f
            for f in os.listdir(photos_dir)
            if os.path.isfile(os.path.join(photos_dir, f))
            and f.lower().endswith(valid_extensions)
        }

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

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

        conn.commit()
        logger.info("Photo database sync complete.")

    except Exception as e:
        logger.error("Error syncing photos: %s", e)
    finally:
        if conn:
            conn.close()


def get_photo_count():
    """Returns the number of photos in the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM background_photos")
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error("Error counting photos: %s", e)
        return 0
    finally:
        conn.close()


def get_random_photo_filename():
    """Fetches a random photo filename from the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT filename FROM background_photos ORDER BY RANDOM() LIMIT 1"
        )
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error("Error fetching random photo: %s", e)
        return None
    finally:
        conn.close()
