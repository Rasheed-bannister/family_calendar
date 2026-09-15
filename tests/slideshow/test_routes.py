"""Tests for src/slideshow/routes.py."""

from unittest.mock import patch

import pytest

from src.main import create_app
from src.slideshow.database import Photo


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestNextPhoto:
    @patch("src.slideshow.routes.slideshow_db")
    def test_returns_the_processed_variant(self, mock_db, client):
        mock_db.next_photo.return_value = Photo("IMG_1.HEIC", "IMG_1.jpg", 1536, 2048)
        mock_db.PHOTOS_STATIC_REL_PATH = "photos"

        response = client.get("/api/slideshow/next")

        assert response.status_code == 200
        data = response.get_json()
        assert data["url"] == "/static/photos/processed/IMG_1.jpg"
        assert data["filename"] == "IMG_1.HEIC"
        assert (data["width"], data["height"]) == (1536, 2048)
        assert data["orientation"] == "portrait"

    @patch("src.slideshow.routes.slideshow_db")
    def test_empty_library(self, mock_db, client):
        mock_db.next_photo.return_value = None
        mock_db.get_photo_count.return_value = 0
        data = client.get("/api/slideshow/next").get_json()
        assert data == {"url": None, "empty": True}

    @patch("src.slideshow.routes.slideshow_db")
    def test_no_photo_but_library_not_empty(self, mock_db, client):
        mock_db.next_photo.return_value = None
        mock_db.get_photo_count.return_value = 5
        data = client.get("/api/slideshow/next").get_json()
        assert data == {"url": None, "empty": False}

    def test_old_endpoint_is_gone(self, client):
        assert client.get("/api/random-photo").status_code == 404


class TestSettings:
    @patch("src.slideshow.routes.slideshow_db")
    def test_reports_config_and_count(self, mock_db, client):
        mock_db.get_photo_count.return_value = 12

        class Cfg:
            def get(self, key, default=None):
                return {
                    "slideshow.interval_seconds": 45,
                    "slideshow.transition_seconds": 3,
                    "slideshow.ken_burns": False,
                }.get(key, default)

        with patch("src.config.get_config", return_value=Cfg()):
            data = client.get("/api/slideshow/settings").get_json()
        assert data == {
            "interval_seconds": 45,
            "transition_seconds": 3,
            "ken_burns": False,
            "photo_count": 12,
        }
