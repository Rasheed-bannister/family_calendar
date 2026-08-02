"""Tests for src/chores_app/routes.py."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src import sync_state
from src.google_integration.routes import TASKS_TASK_ID
from src.main import create_app
from src.sync_state import registry


@pytest.fixture
def client():
    """Create a Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            pass
        yield client


@pytest.fixture
def tasks_state():
    """Isolate the registry's task state for a single test.

    Swapping the attribute (rather than mutating the shared dict) means the
    registry's own methods read the isolated copy, and the real state is
    restored automatically even if the test fails.
    """
    with patch.object(registry, "tasks", {}) as tasks:
        yield tasks


@pytest.fixture
def inline_executor():
    """Replace the shared thread pool with one that runs work synchronously."""
    executor = MagicMock()
    executor.submit.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    with patch.object(registry, "executor", executor):
        yield executor


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


class TestRefreshChores:
    """Regression tests for the /chores/refresh wedge.

    The route used to set the "tasks" entry's status to "running" and then call
    the worker, whose first action is to bail out when the status is already
    "running". The sync never ran, the route reported success, and the status
    stayed "running" forever - blocking every later chores sync.
    """

    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_refresh_actually_fetches_from_google(
        self, mock_tasks_api, mock_chores_db, client, tasks_state, inline_executor
    ):
        mock_tasks_api.get_chores.return_value = []
        mock_chores_db.get_chores.return_value = []

        response = client.post("/chores/refresh")

        # app.js only requires response.ok
        assert response.status_code < 400
        mock_tasks_api.get_chores.assert_called_once()
        assert registry.status(TASKS_TASK_ID) == sync_state.COMPLETE

    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_refresh_does_not_wedge_later_syncs(
        self, mock_tasks_api, mock_chores_db, client, tasks_state, inline_executor
    ):
        mock_tasks_api.get_chores.return_value = []
        mock_chores_db.get_chores.return_value = []

        client.post("/chores/refresh")
        client.post("/chores/refresh")

        assert mock_tasks_api.get_chores.call_count == 2
        assert registry.status(TASKS_TASK_ID) == sync_state.COMPLETE

        # The calendar view's gate must also allow a later sync through. It is
        # staleness-based now: quiet while the result is fresh, open again once
        # the sync interval has elapsed. It used to refuse for any task that had
        # ever completed, so after the first successful chores sync the render
        # path never re-triggered one for the life of the process.
        from src.calendar_app.routes import _should_start_chores_background_task

        assert _should_start_chores_background_task() is False
        registry.update(TASKS_TASK_ID, last_update_time=0)
        assert _should_start_chores_background_task() is True

    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_refresh_reports_in_progress_without_starting_a_second_sync(
        self, mock_tasks_api, mock_chores_db, client, tasks_state
    ):
        registry.update(TASKS_TASK_ID, status=sync_state.RUNNING, updated=False)

        executor = MagicMock()
        with patch.object(registry, "executor", executor):
            response = client.post("/chores/refresh")

        assert response.status_code == 202
        assert response.get_json()["message"] == "Refresh already in progress"
        executor.submit.assert_not_called()
        mock_tasks_api.get_chores.assert_not_called()

    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_refresh_surfaces_worker_error_status(
        self, mock_tasks_api, mock_chores_db, client, tasks_state, inline_executor
    ):
        mock_tasks_api.get_chores.side_effect = RuntimeError("google exploded")

        response = client.post("/chores/refresh")

        assert response.status_code < 400
        # Client polls /calendar/check-updates and needs a terminal status
        assert registry.status(TASKS_TASK_ID) == sync_state.ERROR

    def test_refresh_returns_500_when_sync_cannot_be_queued(self, client, tasks_state):
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("pool is shut down")

        with patch.object(registry, "executor", executor):
            response = client.post("/chores/refresh")

        assert response.status_code == 500
        assert registry.status(TASKS_TASK_ID) == sync_state.ERROR


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
