"""Tests for src/google_integration/routes.py background sync workers."""

from unittest.mock import MagicMock, patch

import pytest

from src import sync_state
from src.google_integration import routes as google_routes
from src.sync_state import registry


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


class TestFetchGoogleEventsBackgroundResilience:
    """Regression tests: the worker must survive its task entry disappearing.

    `registry.clear()` (via `clear_stale_background_tasks()`) wipes the task
    state wholesale, which can happen while a worker is mid-flight. Indexing
    the entry unconditionally used to raise KeyError from inside the try body,
    the except block *and* the finally block, killing the worker thread.
    """

    @patch("src.google_integration.routes.calendar_api")
    @patch("src.google_integration.routes.calendar_db")
    def test_survives_entry_removed_during_success_path(
        self, mock_calendar_db, mock_calendar_api, tasks_state
    ):
        def fetch_and_wipe(month, year):
            registry.clear()  # simulate clear_stale_background_tasks()
            return []

        mock_calendar_api.fetch_and_process_google_events.side_effect = fetch_and_wipe

        google_routes.fetch_google_events_background(5, 2025)

        # No exception, and the entry was recreated rather than lost
        assert registry.status("calendar.5.2025") == sync_state.COMPLETE

    @patch("src.google_integration.routes.calendar_api")
    @patch("src.google_integration.routes.calendar_db")
    def test_survives_entry_removed_during_error_path(
        self, mock_calendar_db, mock_calendar_api, tasks_state
    ):
        def blow_up_and_wipe(month, year):
            registry.clear()  # simulate clear_stale_background_tasks()
            raise RuntimeError("google exploded")

        mock_calendar_api.fetch_and_process_google_events.side_effect = blow_up_and_wipe

        # The error handler itself must not raise
        google_routes.fetch_google_events_background(5, 2025)

        entry = registry.snapshot("calendar.5.2025")
        assert entry["status"] == sync_state.ERROR
        assert entry["events_changed"] is False

    @patch("src.google_integration.routes.calendar_api")
    @patch("src.google_integration.routes.calendar_db")
    def test_normal_run_marks_complete(
        self, mock_calendar_db, mock_calendar_api, tasks_state
    ):
        mock_calendar_api.fetch_and_process_google_events.return_value = []

        google_routes.fetch_google_events_background(5, 2025)

        entry = registry.snapshot("calendar.5.2025")
        assert entry["status"] == sync_state.COMPLETE
        assert entry["events_changed"] is False
        assert "last_update_time" in entry

    def test_skips_when_already_running(self, tasks_state):
        registry.update("calendar.5.2025", status=sync_state.RUNNING, updated=False)

        with patch("src.google_integration.routes.calendar_api") as mock_calendar_api:
            google_routes.fetch_google_events_background(5, 2025)

        mock_calendar_api.fetch_and_process_google_events.assert_not_called()
        assert registry.status("calendar.5.2025") == sync_state.RUNNING


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
        assert registry.status(google_routes.TASKS_TASK_ID) == sync_state.COMPLETE

    def test_skips_when_already_pending(self, tasks_state):
        registry.update(
            google_routes.TASKS_TASK_ID, status=sync_state.PENDING, updated=False
        )

        executor = MagicMock()
        with patch.object(registry, "executor", executor):
            assert google_routes.start_tasks_sync() is False

        executor.submit.assert_not_called()

    def test_skips_when_already_running(self, tasks_state):
        registry.update(
            google_routes.TASKS_TASK_ID, status=sync_state.RUNNING, updated=False
        )

        executor = MagicMock()
        with patch.object(registry, "executor", executor):
            assert google_routes.start_tasks_sync() is False

        executor.submit.assert_not_called()

    def test_restarts_after_error(self, tasks_state):
        registry.update(
            google_routes.TASKS_TASK_ID, status=sync_state.ERROR, updated=False
        )

        executor = MagicMock()
        with patch.object(registry, "executor", executor):
            assert google_routes.start_tasks_sync() is True

        executor.submit.assert_called_once()
        assert registry.status(google_routes.TASKS_TASK_ID) == sync_state.PENDING

    def test_submit_failure_marks_error(self, tasks_state):
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("pool is shut down")

        with patch.object(registry, "executor", executor):
            with pytest.raises(RuntimeError):
                google_routes.start_tasks_sync()

        # Status must not stay latched at pending, or nothing can sync again
        assert registry.status(google_routes.TASKS_TASK_ID) == sync_state.ERROR


class TestFetchGoogleTasksBackgroundResilience:
    @patch("src.google_integration.routes.chores_db")
    @patch("src.google_integration.routes.tasks_api")
    def test_survives_entry_removed_mid_flight(
        self, mock_tasks_api, mock_chores_db, tasks_state
    ):
        def fetch_and_wipe():
            registry.clear()
            return []

        mock_tasks_api.get_chores.side_effect = fetch_and_wipe
        mock_chores_db.get_chores.return_value = []

        google_routes.fetch_google_tasks_background()

        assert registry.status(google_routes.TASKS_TASK_ID) == sync_state.COMPLETE
