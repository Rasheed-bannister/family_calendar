import os
import sqlite3

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "slideshow.db")
PHOTOS_STATIC_REL_PATH = "photos"  # Relative path within the static folder


def init_db():
    """Initializes the slideshow database and creates the table if it doesn't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS background_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL
        )
    """
    )
    conn.commit()
    conn.close()
    print("Slideshow database initialized.")


def sync_photos(static_folder_path):
    """Scans the photos directory and updates the database."""
    photos_dir = os.path.join(static_folder_path, PHOTOS_STATIC_REL_PATH)
    if not os.path.isdir(photos_dir):
        print(f"Photos directory not found: {photos_dir}")
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

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Get files currently in the database
        cursor.execute("SELECT filename FROM background_photos")
        db_files = {row[0] for row in cursor.fetchall()}

        # Add new files
        files_to_add = current_files - db_files
        if files_to_add:
            print(f"Adding {len(files_to_add)} new photos to DB: {files_to_add}")
            cursor.executemany(
                "INSERT OR IGNORE INTO background_photos (filename) VALUES (?)",
                [(f,) for f in files_to_add],
            )

        # Remove files no longer present
        files_to_remove = db_files - current_files
        if files_to_remove:
            print(f"Removing {len(files_to_remove)} photos from DB: {files_to_remove}")
            cursor.executemany(
                "DELETE FROM background_photos WHERE filename = ?",
                [(f,) for f in files_to_remove],
            )

        conn.commit()
        conn.close()
        print("Photo database sync complete.")

    except Exception as e:
        print(f"Error syncing photos: {e}")
        if conn:
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
        print(f"Error fetching random photo: {e}")
        return None
    finally:
        conn.close()
