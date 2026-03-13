"""Tests for src/slideshow/database.py."""

import os
import sqlite3
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


class TestInitDb:
    """Tests for init_db."""

    def test_creates_table(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        with patch.object(slideshow_db, "DATABASE_PATH", db_path):
            slideshow_db.init_db()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
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
