"""Tests for the background sync registry.

The registry exists to make two specific outages impossible by construction,
so those two scenarios are tested directly rather than only through the
routes that used to get them wrong:

* a caller writing a status the worker then refuses to take over, wedging
  the task at ``running`` forever;
* a worker's own error handler raising KeyError because its entry was
  cleared mid-flight.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from src import sync_state
from src.sync_state import SyncRegistry


@pytest.fixture
def reg():
    """A registry with an inert executor, so nothing actually runs."""
    r = SyncRegistry()
    r.executor = Mock()
    return r


class TestClaim:
    def test_claim_parks_task_at_pending(self, reg):
        assert reg.claim("t") is True
        assert reg.status("t") == sync_state.PENDING

    def test_claim_refuses_when_pending(self, reg):
        reg.claim("t")
        assert reg.claim("t") is False

    def test_claim_refuses_when_running(self, reg):
        reg.mark_running("t")
        assert reg.claim("t") is False

    def test_claim_allowed_again_after_completion(self, reg):
        reg.claim("t")
        reg.mark_running("t")
        reg.finalize("t")
        assert reg.claim("t") is True

    def test_claim_allowed_again_after_error(self, reg):
        reg.claim("t")
        reg.update("t", status=sync_state.ERROR)
        assert reg.claim("t") is True, "an errored task must not block retries"

    def test_initial_fields_are_stored(self, reg):
        reg.claim("t", chores_changed=False)
        assert reg.snapshot("t")["chores_changed"] is False


class TestSubmitIsTheOnlyEntryPoint:
    def test_submit_claims_and_queues(self, reg):
        fn = Mock()
        assert reg.submit("t", fn, 1, 2) is True
        reg.executor.submit.assert_called_once_with(fn, 1, 2)
        assert reg.status("t") == sync_state.PENDING

    def test_submit_refuses_when_already_in_flight(self, reg):
        reg.submit("t", Mock())
        reg.executor.submit.reset_mock()

        assert reg.submit("t", Mock()) is False
        reg.executor.submit.assert_not_called()

    def test_submit_does_not_leave_task_pending_when_pool_rejects(self, reg):
        """A rejected submit must not latch the task at PENDING.

        PENDING counts as in-flight, so leaving it there would block every
        future sync of that task -- the exact wedge this class prevents.
        """
        reg.executor.submit.side_effect = RuntimeError("pool is shut down")

        with pytest.raises(RuntimeError):
            reg.submit("t", Mock())

        assert reg.status("t") == sync_state.ERROR
        assert reg.is_in_flight("t") is False
        assert reg.claim("t") is True, "task must be runnable again"

    def test_worker_can_take_over_a_submitted_task(self, reg):
        """The regression: a claim must not block the worker that follows it.

        The chores outage was a caller setting "running" and then invoking the
        worker, whose first act is to bail out if the status is already
        "running". submit() parks at PENDING precisely so mark_running()
        succeeds.
        """
        reg.submit("t", Mock())
        assert reg.mark_running("t") is True


class TestMarkRunning:
    def test_second_worker_backs_off(self, reg):
        assert reg.mark_running("t") is True
        assert reg.mark_running("t") is False

    def test_untracked_task_can_be_marked(self, reg):
        assert reg.mark_running("never-seen") is True


class TestVanishingEntries:
    """Workers must survive their entry being cleared mid-flight.

    ``clear()`` runs at startup and wipes the dict. A worker already running
    would previously raise KeyError from inside its own except/finally block,
    killing the thread and losing the original error.
    """

    def test_update_recreates_a_cleared_entry(self, reg):
        reg.mark_running("t")
        reg.clear()
        reg.update("t", updated=True)  # must not raise
        assert reg.snapshot("t")["updated"] is True

    def test_finalize_recreates_a_cleared_entry(self, reg):
        reg.mark_running("t")
        reg.clear()
        reg.finalize("t")  # must not raise
        assert reg.status("t") == sync_state.COMPLETE

    def test_consume_flag_on_cleared_entry_is_false(self, reg):
        reg.update("t", events_changed=True)
        reg.clear()
        assert reg.consume_flag("t", "events_changed") is False

    def test_snapshot_of_missing_task_is_none(self, reg):
        assert reg.snapshot("nope") is None
        assert reg.status("nope") is None


class TestFinalize:
    def test_finalize_marks_complete(self, reg):
        reg.mark_running("t")
        reg.finalize("t")
        assert reg.status("t") == sync_state.COMPLETE

    def test_finalize_preserves_error(self, reg):
        reg.mark_running("t")
        reg.update("t", status=sync_state.ERROR)
        reg.finalize("t")
        assert reg.status("t") == sync_state.ERROR

    def test_finalize_stamps_time_on_error_path_too(self, reg):
        """Errors must reset the staleness clock or a failing sync retries hot."""
        reg.mark_running("t")
        reg.update("t", status=sync_state.ERROR)
        reg.finalize("t")
        assert reg.snapshot("t")["last_update_time"] > 0
        assert reg.is_stale("t", 3600) is False


class TestConsumeFlag:
    def test_returns_true_once_then_clears(self, reg):
        reg.update("t", events_changed=True)
        assert reg.consume_flag("t", "events_changed") is True
        assert reg.consume_flag("t", "events_changed") is False

    def test_false_when_flag_unset(self, reg):
        reg.update("t", events_changed=False)
        assert reg.consume_flag("t", "events_changed") is False

    def test_clears_the_companion_updated_field(self, reg):
        reg.update("t", events_changed=True, updated=True)
        reg.consume_flag("t", "events_changed")
        assert reg.snapshot("t")["updated"] is False


class TestIsStale:
    def test_untracked_task_is_stale(self, reg):
        assert reg.is_stale("never-run", 60) is True

    def test_in_flight_task_is_never_stale(self, reg):
        reg.claim("t")
        assert reg.is_stale("t", 0) is False, "a refresh is already coming"
        reg.mark_running("t")
        assert reg.is_stale("t", 0) is False

    def test_recently_finished_task_is_fresh(self, reg):
        reg.mark_running("t")
        reg.finalize("t")
        assert reg.is_stale("t", 3600) is False

    def test_long_finished_task_is_stale(self, reg):
        reg.mark_running("t")
        reg.finalize("t")
        reg.update("t", last_update_time=time.time() - 7200)
        assert reg.is_stale("t", 3600) is True


class TestThreadSafety:
    def test_only_one_of_many_racing_claims_wins(self):
        """The claim must be atomic: duplicate syncs waste Google API quota."""
        reg = SyncRegistry()
        reg.executor = Mock()
        winners = []
        barrier = threading.Barrier(16)

        def contend():
            barrier.wait()
            if reg.claim("t"):
                winners.append(threading.current_thread().name)

        threads = [threading.Thread(target=contend) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(winners) == 1

    def test_concurrent_updates_do_not_lose_fields(self):
        reg = SyncRegistry()
        reg.executor = Mock()
        reg.mark_running("t")

        def write(i):
            reg.update("t", **{f"field_{i}": i})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(64)))

        snap = reg.snapshot("t")
        for i in range(64):
            assert snap[f"field_{i}"] == i

    def test_snapshot_is_a_copy(self, reg):
        reg.update("t", updated=True)
        snap = reg.snapshot("t")
        snap["updated"] = "mutated"
        assert reg.snapshot("t")["updated"] is True

    def test_lock_is_reentrant(self, reg):
        """submit() claims while holding the lock; a plain Lock would deadlock."""
        with reg.lock:
            assert reg.claim("t") is True


class TestMainAliasesShareIdentity:
    def test_main_exposes_the_registry_objects(self):
        """The back-compat aliases must be the same objects, not copies."""
        from src import main

        assert main.background_tasks is sync_state.registry.tasks
        assert main.google_fetch_lock is sync_state.registry.lock
        assert main.sync_executor is sync_state.registry.executor
