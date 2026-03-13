"""Tests for src/chores_app/routes.py."""

import json
from unittest.mock import MagicMock, patch

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


class TestUpdateStatus:
    """Tests for the update_status route."""

    @patch("src.chores_app.routes.tasks_api")
    @patch("src.chores_app.routes.db")
    def test_valid_completed_status(self, mock_db, mock_tasks_api, client):
        response = client.post(
            "/chores/update_status/chore-1",
            data=json.dumps({"status": "completed"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True
        mock_db.update_chore_status.assert_called_once_with("chore-1", "completed")
        mock_tasks_api.mark_chore_completed.assert_called_once_with("chore-1")

    @patch("src.chores_app.routes.tasks_api")
    @patch("src.chores_app.routes.db")
    def test_valid_needs_action_status(self, mock_db, mock_tasks_api, client):
        response = client.post(
            "/chores/update_status/chore-1",
            data=json.dumps({"status": "needsAction"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        mock_db.update_chore_status.assert_called_once_with("chore-1", "needsAction")
        mock_tasks_api.update_chore.assert_called_once_with(
            "chore-1", updates={"status": "needsAction"}
        )

    @patch("src.chores_app.routes.tasks_api")
    @patch("src.chores_app.routes.db")
    def test_invisible_status_local_only(self, mock_db, mock_tasks_api, client):
        """Invisible status should only update local DB, not Google."""
        response = client.post(
            "/chores/update_status/chore-1",
            data=json.dumps({"status": "invisible"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        mock_db.update_chore_status.assert_called_once_with("chore-1", "invisible")
        mock_tasks_api.mark_chore_completed.assert_not_called()
        mock_tasks_api.update_chore.assert_not_called()

    def test_invalid_status(self, client):
        response = client.post(
            "/chores/update_status/chore-1",
            data=json.dumps({"status": "invalid_status"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_missing_status(self, client):
        response = client.post(
            "/chores/update_status/chore-1",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestAddChoreRoute:
    """Tests for the add_chore_route."""

    @patch("src.chores_app.routes.tasks_api")
    @patch("src.chores_app.routes.db")
    def test_add_chore_success(self, mock_db, mock_tasks_api, client):
        mock_chore = MagicMock()
        mock_chore.id = "local-uuid-123"
        mock_db.add_chore.return_value = mock_chore
        mock_tasks_api.create_chore.return_value = {"id": "google-task-789"}

        response = client.post(
            "/chores/add",
            data=json.dumps({"title": "Alice", "notes": "Do dishes"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["id"] == "google-task-789"
        mock_db.update_chore_google_id.assert_called_once_with(
            "local-uuid-123", "google-task-789"
        )

    @patch("src.chores_app.routes.tasks_api")
    @patch("src.chores_app.routes.db")
    def test_add_chore_google_fails(self, mock_db, mock_tasks_api, client):
        """Chore should still be added locally even if Google sync fails."""
        mock_chore = MagicMock()
        mock_chore.id = "local-uuid-123"
        mock_db.add_chore.return_value = mock_chore
        mock_tasks_api.create_chore.return_value = None

        response = client.post(
            "/chores/add",
            data=json.dumps({"title": "Alice", "notes": "Do dishes"}),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["success"] is True
        assert data["id"] == "local-uuid-123"
        mock_db.update_chore_google_id.assert_not_called()

    def test_add_chore_missing_title(self, client):
        response = client.post(
            "/chores/add",
            data=json.dumps({"notes": "Do dishes"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_add_chore_missing_notes(self, client):
        response = client.post(
            "/chores/add",
            data=json.dumps({"title": "Alice"}),
            content_type="application/json",
        )
        assert response.status_code == 400
