"""Tests for src/slideshow/routes.py."""

from unittest.mock import patch

import pytest

from src.main import create_app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            pass
        yield client


class TestRandomPhotoEndpoint:
    """Tests for /api/random-photo endpoint."""

    @patch("src.slideshow.routes.slideshow_db")
    def test_returns_photo_url(self, mock_db, client):
        mock_db.get_random_photo_filename.return_value = "photo1.jpg"
        mock_db.PHOTOS_STATIC_REL_PATH = "photos"

        response = client.get("/api/random-photo")
        assert response.status_code == 200
        data = response.get_json()
        assert data["url"] is not None
        assert "photo1.jpg" in data["url"]

    @patch("src.slideshow.routes.slideshow_db")
    def test_empty_library_returns_200_with_empty_flag(self, mock_db, client):
        """When no photos exist, should return 200 with empty=true, not 404."""
        mock_db.get_random_photo_filename.return_value = None
        mock_db.get_photo_count.return_value = 0

        response = client.get("/api/random-photo")
        assert response.status_code == 200
        data = response.get_json()
        assert data["url"] is None
        assert data["empty"] is True

    @patch("src.slideshow.routes.slideshow_db")
    def test_no_photo_returned_but_library_not_empty(self, mock_db, client):
        """Edge case: random query returns None but photos exist (unlikely but possible)."""
        mock_db.get_random_photo_filename.return_value = None
        mock_db.get_photo_count.return_value = 5

        response = client.get("/api/random-photo")
        assert response.status_code == 200
        data = response.get_json()
        assert data["url"] is None
        assert data["empty"] is False
