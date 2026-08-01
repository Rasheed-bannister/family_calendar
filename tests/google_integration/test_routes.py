"""Tests for src/google_integration/routes.py background sync workers."""

from unittest.mock import MagicMock, patch

import pytest

from src.google_integration import routes as google_routes
from src.main import background_tasks


@pytest.fixture
def tasks_state():
    """Isolate the module-global background_tasks dict for a single test."""
    snapshot = dict(background_tasks)
    background_tasks.clear()
    yield background_tasks
    background_tasks.clear()
    background_tasks.update(snapshot)


@pytest.fixture
def inline_executor():
    """Replace the shared thread pool with one that runs work synchronously."""
    executor = MagicMock()
    executor.submit.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    with patch("src.main.sync_executor", executor):
        yield executor


class TestFetchGoogleEventsBackgroundResilience:
    """Regression tests: the worker must survive its task entry disappearing.

    `clear_stale_background_tasks()` wipes `background_tasks` wholesale, which
    can happen while a worker is mid-flight. Indexing the entry unconditionally
    used to raise KeyError from inside the try body, the except block *and* the
    finally block, killing the worker thread.
    """

    @patch("src.google_integration.routes.calendar_api")
    @patch("src.google_integration.routes.calendar_db")
    def test_survives_entry_removed_during_success_path(
        self, mock_calendar_db, mock_calendar_api, tasks_state
    ):
        def fetch_and_wipe(month, year):
            background_tasks.clear()  # simulate clear_stale_background_tasks()
            return []

        mock_calendar_api.fetch_and_process_google_events.side_effect = fetch_and_wipe

        google_routes.fetch_google_events_background(5, 2025)

        # No exception, and the entry was recreated rather than lost
        assert tasks_state["calendar.5.2025"]["status"] == "complete"

    @patch("src.google_integration.routes.calendar_api")
    @patch("src.google_integration.routes.calendar_db")
    def test_survives_entry_removed_during_error_path(
        self, mock_calendar_db, mock_calendar_api, tasks_state
    ):
        def blow_up_and_wipe(month, year):
            background_tasks.clear()  # simulate clear_stale_background_tasks()
            raise RuntimeError("google exploded")

        mock_calendar_api.fetch_and_process_google_events.side_effect = blow_up_and_wipe

        # The error handler itself must not raise
        google_routes.fetch_google_events_background(5, 2025)

        assert tasks_state["calendar.5.2025"]["status"] == "error"
        assert tasks_state["calendar.5.2025"]["events_changed"] is False

    @patch("src.google_integration.routes.calendar_api")
    @patch("src.google_integration.routes.calendar_db")
    def test_normal_run_marks_complete(
        self, mock_calendar_db, mock_calendar_api, tasks_state
    ):
        mock_calendar_api.fetch_and_process_google_events.return_value = []

        google_routes.fetch_google_events_background(5, 2025)

        entry = tasks_state["calendar.5.2025"]
        assert entry["status"] == "complete"
        assert entry["events_changed"] is False
        assert "last_update_time" in entry

    def test_skips_when_already_running(self, tasks_state):
        tasks_state["calendar.5.2025"] = {"status": "running", "updated": False}

        with patch("src.google_integration.routes.calendar_api") as mock_calendar_api:
            google_routes.fetch_google_events_background(5, 2025)

        mock_calendar_api.fetch_and_process_google_events.assert_not_called()
        assert tasks_state["calendar.5.2025"]["status"] == "running"


class TestStartTasksSync:
    """The starter claims the slot; the worker owns the status lifecycle."""

    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_claim_leaves_task_runnable(
        self, mock_tasks_api, mock_chores_db, tasks_state, inline_executor
    ):
        """A claimed ("pending") task must not be rejected by the worker."""
        mock_tasks_api.get_chores.return_value = []
        mock_chores_db.get_chores.return_value = []

        assert google_routes.start_tasks_sync() is True

        inline_executor.submit.assert_called_once()
        mock_tasks_api.get_chores.assert_called_once()
        assert tasks_state["tasks"]["status"] == "complete"

    def test_skips_when_already_pending(self, tasks_state):
        tasks_state["tasks"] = {"status": "pending", "updated": False}

        executor = MagicMock()
        with patch("src.main.sync_executor", executor):
            assert google_routes.start_tasks_sync() is False

        executor.submit.assert_not_called()

    def test_skips_when_already_running(self, tasks_state):
        tasks_state["tasks"] = {"status": "running", "updated": False}

        executor = MagicMock()
        with patch("src.main.sync_executor", executor):
            assert google_routes.start_tasks_sync() is False

        executor.submit.assert_not_called()

    def test_restarts_after_error(self, tasks_state):
        tasks_state["tasks"] = {"status": "error", "updated": False}

        executor = MagicMock()
        with patch("src.main.sync_executor", executor):
            assert google_routes.start_tasks_sync() is True

        executor.submit.assert_called_once()
        assert tasks_state["tasks"]["status"] == "pending"

    def test_submit_failure_marks_error(self, tasks_state):
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("pool is shut down")

        with patch("src.main.sync_executor", executor):
            with pytest.raises(RuntimeError):
                google_routes.start_tasks_sync()

        # Status must not stay latched at pending, or nothing can sync again
        assert tasks_state["tasks"]["status"] == "error"


class TestFetchGoogleTasksBackgroundResilience:
    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_survives_entry_removed_mid_flight(
        self, mock_tasks_api, mock_chores_db, tasks_state
    ):
        def fetch_and_wipe():
            background_tasks.clear()
            return []

        mock_tasks_api.get_chores.side_effect = fetch_and_wipe
        mock_chores_db.get_chores.return_value = []

        google_routes.fetch_google_tasks_background()

        assert tasks_state["tasks"]["status"] == "complete"
