"""Tests for the periodic sync scheduler.

The scheduling logic is exercised synchronously through ``run_due_jobs`` with
an explicit clock, so nothing here sleeps. Only the small number of tests that
genuinely cover thread lifecycle start a thread.
"""

import threading
import time
from unittest.mock import Mock, patch

import pytest

from src.scheduler import SyncScheduler


@pytest.fixture
def sched():
    s = SyncScheduler(thread_name="test-scheduler")
    yield s
    s.stop(timeout=2)


class TestJobRegistrationAndFiring:
    def test_job_runs_immediately_on_first_tick(self, sched):
        fn = Mock()
        sched.add_job("j", fn, interval=60)
        sched.run_due_jobs(now=1000.0)
        fn.assert_called_once()

    def test_run_immediately_false_defers_first_run(self, sched):
        fn = Mock()
        with patch("src.scheduler.time.monotonic", return_value=1000.0):
            sched.add_job("j", fn, interval=60, run_immediately=False)
        sched.run_due_jobs(now=1000.0)
        fn.assert_not_called()

        sched.run_due_jobs(now=1061.0)
        fn.assert_called_once()

    def test_job_does_not_refire_before_its_interval(self, sched):
        fn = Mock()
        sched.add_job("j", fn, interval=60)
        sched.run_due_jobs(now=1000.0)
        sched.run_due_jobs(now=1030.0)
        sched.run_due_jobs(now=1059.0)
        assert fn.call_count == 1

    def test_job_refires_after_its_interval(self, sched):
        fn = Mock()
        sched.add_job("j", fn, interval=60)
        sched.run_due_jobs(now=1000.0)
        sched.run_due_jobs(now=1061.0)
        assert fn.call_count == 2

    def test_independent_jobs_keep_independent_schedules(self, sched):
        fast, slow = Mock(), Mock()
        sched.add_job("fast", fast, interval=10)
        sched.add_job("slow", slow, interval=100)
        for t in (1000.0, 1011.0, 1022.0, 1033.0):
            sched.run_due_jobs(now=t)
        assert fast.call_count == 4
        assert slow.call_count == 1

    def test_returns_names_of_jobs_run(self, sched):
        sched.add_job("a", Mock(), interval=10)
        sched.add_job("b", Mock(), interval=1000)
        assert set(sched.run_due_jobs(now=1000.0)) == {"a", "b"}
        assert sched.run_due_jobs(now=1011.0) == ["a"]


class TestFailureIsolation:
    def test_failing_job_does_not_stop_other_jobs(self, sched):
        boom = Mock(side_effect=RuntimeError("network down"))
        ok = Mock()
        sched.add_job("boom", boom, interval=10)
        sched.add_job("ok", ok, interval=10)

        sched.run_due_jobs(now=1000.0)

        ok.assert_called_once(), "a failing job must not starve its neighbours"

    def test_failing_job_does_not_propagate(self, sched):
        sched.add_job("boom", Mock(side_effect=RuntimeError("x")), interval=10)
        sched.run_due_jobs(now=1000.0)  # must not raise

    def test_failing_job_is_rescheduled_not_retried_hot(self, sched):
        """A job that fails must back off, not fire on every single tick."""
        boom = Mock(side_effect=RuntimeError("x"))
        sched.add_job("boom", boom, interval=60)

        sched.run_due_jobs(now=1000.0)
        sched.run_due_jobs(now=1001.0)
        sched.run_due_jobs(now=1002.0)

        assert boom.call_count == 1

    def test_failure_is_recorded_for_the_health_endpoint(self, sched):
        sched.add_job("boom", Mock(side_effect=RuntimeError("no network")), interval=10)
        sched.run_due_jobs(now=1000.0)

        status = {j["name"]: j for j in sched.job_status()}["boom"]
        assert status["error_count"] == 1
        assert status["run_count"] == 0
        assert "no network" in status["last_error"]

    def test_slow_job_does_not_stack_up(self, sched):
        """Rescheduling happens before the call, so a long job cannot re-fire."""
        calls = []

        def slow():
            calls.append(1)

        sched.add_job("slow", slow, interval=60)
        sched.run_due_jobs(now=1000.0)
        # A tick arriving while the previous run was still in progress would
        # have `now` only slightly later; next_due was already pushed forward.
        sched.run_due_jobs(now=1005.0)
        assert len(calls) == 1


class TestIntervalResolution:
    def test_callable_interval_is_re_read_each_time(self, sched):
        current = {"v": 10}
        fn = Mock()
        sched.add_job("j", fn, interval=lambda: current["v"])

        sched.run_due_jobs(now=1000.0)
        current["v"] = 1000  # config changed at runtime
        sched.run_due_jobs(now=1011.0)
        assert fn.call_count == 2

        # Now on the longer interval, so this tick is too early.
        sched.run_due_jobs(now=1100.0)
        assert fn.call_count == 2

    def test_bad_interval_falls_back_instead_of_raising(self, sched):
        fn = Mock()
        sched.add_job("j", fn, interval=lambda: "not a number")
        sched.run_due_jobs(now=1000.0)  # must not raise
        fn.assert_called_once()

    @pytest.mark.parametrize("bad", [0, -5])
    def test_non_positive_interval_does_not_busy_loop(self, sched, bad):
        fn = Mock()
        sched.add_job("j", fn, interval=bad)
        sched.run_due_jobs(now=1000.0)
        sched.run_due_jobs(now=1001.0)
        assert fn.call_count == 1, "a 0/negative interval must not fire every tick"


class TestThreadLifecycle:
    def test_start_and_stop(self, sched):
        assert sched.is_running is False
        assert sched.start(tick_seconds=0.01) is True
        assert sched.is_running is True
        sched.stop(timeout=2)
        assert sched.is_running is False

    def test_double_start_is_refused(self, sched):
        sched.start(tick_seconds=0.05)
        assert sched.start(tick_seconds=0.05) is False
        sched.stop(timeout=2)

    def test_thread_actually_runs_jobs(self, sched):
        fired = threading.Event()
        sched.add_job("j", fired.set, interval=60)
        sched.start(tick_seconds=0.01)
        assert fired.wait(timeout=3.0), "scheduler thread never ran the job"
        sched.stop(timeout=2)

    def test_stop_is_prompt_despite_a_long_tick(self, sched):
        """stop() uses Event.wait, so it must not block for a whole tick."""
        sched.add_job("j", Mock(), interval=60)
        sched.start(tick_seconds=30.0)
        started = time.monotonic()
        sched.stop(timeout=5)
        assert time.monotonic() - started < 2.0
        assert sched.is_running is False

    def test_thread_survives_a_failing_job(self, sched):
        ok = threading.Event()
        sched.add_job("boom", Mock(side_effect=RuntimeError("x")), interval=0.01)
        sched.add_job("ok", ok.set, interval=0.01)
        sched.start(tick_seconds=0.01)
        assert ok.wait(timeout=3.0)
        assert sched.is_running is True
        sched.stop(timeout=2)

    def test_stop_is_safe_when_never_started(self, sched):
        sched.stop(timeout=1)  # must not raise
        assert sched.is_running is False


class TestRegisteredApplicationJobs:
    """The wiring in src.main: jobs must queue work, never block the thread."""

    def test_register_sync_jobs_registers_all_three(self):
        from src.main import register_sync_jobs

        s = SyncScheduler()
        register_sync_jobs(s)
        assert {j["name"] for j in s.job_status()} == {"calendar", "chores", "weather"}

    def test_jobs_use_configured_intervals(self):
        from src.main import register_sync_jobs

        s = SyncScheduler()
        register_sync_jobs(s)
        by_name = {j["name"]: j for j in s.job_status()}
        # google.sync_interval_minutes is in minutes; weather.cache_duration in seconds.
        assert by_name["calendar"]["interval_seconds"] >= 60
        assert by_name["chores"]["interval_seconds"] >= 60
        assert by_name["weather"]["interval_seconds"] > 0

    def test_calendar_job_targets_todays_month(self):
        from src.main import _sync_current_month_calendar

        with patch("src.google_integration.routes.start_calendar_sync") as start:
            with patch("src.sync_state.registry.is_stale", return_value=True):
                _sync_current_month_calendar()

        start.assert_called_once()
        month, year = start.call_args[0]
        import datetime

        from src.config import get_local_timezone

        now = datetime.datetime.now(tz=get_local_timezone())
        assert (month, year) == (now.month, now.year)

    def test_calendar_job_skips_when_data_is_fresh(self):
        from src.main import _sync_current_month_calendar

        with patch("src.google_integration.routes.start_calendar_sync") as start:
            with patch("src.sync_state.registry.is_stale", return_value=False):
                _sync_current_month_calendar()
        start.assert_not_called()

    def test_chores_job_skips_when_data_is_fresh(self):
        from src.main import _sync_chores

        with patch("src.google_integration.routes.start_tasks_sync") as start:
            with patch("src.sync_state.registry.is_stale", return_value=False):
                _sync_chores()
        start.assert_not_called()

    def test_jobs_do_not_block_on_the_network(self):
        """Each job only queues onto the registry's pool.

        If a job called the Google API inline, one unreachable network would
        stall every other job behind it on the single scheduler thread.
        """
        from src.main import _sync_chores
        from src.sync_state import registry

        with patch.object(registry, "executor") as ex:
            with patch("src.sync_state.registry.is_stale", return_value=True):
                _sync_chores()
        ex.submit.assert_called_once()


class TestSchedulerIsOptIn:
    def test_create_app_does_not_start_a_scheduler(self):
        """458 tests build the app; none should spawn a syncing thread."""
        from src.main import create_app
        from src.scheduler import scheduler as global_scheduler

        create_app()
        assert global_scheduler.is_running is False

    def test_start_background_sync_respects_the_config_flag(self):
        from src.main import start_background_sync

        mock_config = Mock()
        mock_config.get.return_value = False
        with patch("src.main.get_config", return_value=mock_config):
            s = start_background_sync()
        assert s.is_running is False
