"""Tests for the /health/* endpoints.

These endpoints are the only way to answer "is the Pi healthy, and is it
actually syncing?" without an SSH session, and the HTTP status code of
``/health/`` is the contract an external uptime check consumes. Both were
entirely untested.

Everything here patches the seams the routes actually use -- the
``health_monitor`` singleton, ``src.sync_state.registry`` and
``src.scheduler.scheduler`` -- with ``patch.object``, so the shared global
state is restored even when an assertion fails and no test leaks into the rest
of the suite.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.health_monitor import health_monitor
from src.main import create_app
from src.scheduler import SyncScheduler
from src.sync_state import COMPLETE, RUNNING, registry


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def monitoring_flag():
    """Isolate ``monitoring_enabled`` so the enable/disable routes cannot leak.

    patch.object restores the value it captured on entry regardless of what the
    endpoint set it to in between, which is exactly the guarantee needed for a
    route whose whole job is mutating a global.
    """
    with patch.object(health_monitor, "monitoring_enabled", True):
        yield


def _health_payload(status="healthy", issues=None):
    """A check_health() return value with the fields the route reads."""
    return {
        "status": status,
        "issues": issues or [],
        "system_info": {"uptime_seconds": 1.0},
        "monitoring_enabled": True,
    }


def assert_json_error(response, expected_status):
    """A failing endpoint must answer JSON, never Flask's HTML error page.

    Every client of these routes parses the body as JSON; an HTML 500 turns a
    legible failure into a parse error at the caller.
    """
    assert response.status_code == expected_status
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.get_json() is not None


# --- /health/ ------------------------------------------------------------


@pytest.mark.parametrize("status", ["healthy", "warning"])
def test_health_check_operational_statuses_return_200(client, status):
    """healthy and warning are both "still serving traffic"."""
    with patch.object(
        health_monitor, "check_health", return_value=_health_payload(status)
    ):
        response = client.get("/health/")

    assert response.status_code == 200
    assert response.get_json()["status"] == status


def test_health_check_critical_returns_503(client):
    """The status-code contract an uptime check depends on.

    A body saying "critical" behind a 200 is invisible to every monitoring
    tool that only looks at the code, which is most of them.
    """
    with patch.object(
        health_monitor,
        "check_health",
        return_value=_health_payload("critical", ["Low disk space"]),
    ):
        response = client.get("/health/")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "critical"
    assert body["issues"] == ["Low disk space"]


def test_health_check_reports_real_monitor_shape(client):
    """Unpatched, the endpoint returns the documented keys."""
    response = client.get("/health/")

    assert response.status_code in (200, 503)
    body = response.get_json()
    assert set(body) >= {"status", "issues", "system_info", "monitoring_enabled"}
    assert body["status"] in ("healthy", "warning", "critical")
    assert isinstance(body["issues"], list)


def test_health_check_failure_returns_json_not_html(client):
    with patch.object(
        health_monitor, "check_health", side_effect=RuntimeError("psutil exploded")
    ):
        response = client.get("/health/")

    assert_json_error(response, 500)
    assert response.get_json()["status"] == "error"


# --- /health/detailed ----------------------------------------------------


def test_detailed_health_returns_three_sections(client):
    response = client.get("/health/detailed")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"health", "system", "databases"}
    assert body["health"]["status"] in ("healthy", "warning", "critical")
    assert isinstance(body["databases"], dict)


def test_detailed_health_failure_returns_json_not_html(client):
    with patch.object(
        health_monitor, "get_system_info", side_effect=RuntimeError("no /proc")
    ):
        response = client.get("/health/detailed")

    assert_json_error(response, 500)
    assert response.get_json()["status"] == "error"


# --- /health/system ------------------------------------------------------


def test_system_resources_shape(client):
    response = client.get("/health/system")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) >= {"timestamp", "uptime_seconds", "system", "process", "errors"}
    assert set(body["system"]) >= {"cpu_percent", "memory_percent", "disk_percent"}
    assert body["process"]["pid"] > 0


def test_system_resources_failure_returns_json_not_html(client):
    with patch.object(
        health_monitor, "get_system_info", side_effect=RuntimeError("psutil exploded")
    ):
        response = client.get("/health/system")

    assert_json_error(response, 500)
    assert "error" in response.get_json()


# --- /health/databases ---------------------------------------------------


def test_database_status_reports_each_file(client):
    fake = {
        "src/chores_app/chores.db": {
            "exists": True,
            "size_bytes": 4096,
            "modified": "2025-01-01T00:00:00",
            "readable": True,
            "writable": True,
        },
        "src/slideshow/slideshow.db": {
            "exists": False,
            "error": "Database file not found",
        },
    }
    with patch.object(health_monitor, "get_database_status", return_value=fake):
        response = client.get("/health/databases")

    assert response.status_code == 200
    body = response.get_json()
    assert body["src/chores_app/chores.db"]["exists"] is True
    assert body["src/slideshow/slideshow.db"]["exists"] is False


def test_database_status_real_monitor_returns_exists_flags(client):
    """Unpatched, every reported database carries an ``exists`` verdict."""
    response = client.get("/health/databases")

    assert response.status_code == 200
    body = response.get_json()
    assert body  # at least the two statically listed databases
    assert all("exists" in entry for entry in body.values())


def test_database_status_failure_returns_json_not_html(client):
    with patch.object(
        health_monitor, "get_database_status", side_effect=OSError("disk gone")
    ):
        response = client.get("/health/databases")

    assert_json_error(response, 500)
    assert "error" in response.get_json()


def test_database_status_includes_the_calendar_database(client):
    """The calendar database must be reported.

    It previously never was: the code globbed for ``calendar_*.db`` while the
    file is ``calendar.db``, so the app's primary database was invisible to
    the health endpoint from any working directory.
    """
    body = client.get("/health/databases").get_json()

    names = {entry.get("name") for entry in body.values()}
    assert {"calendar", "chores", "slideshow"} <= names


def test_database_status_is_independent_of_working_directory(tmp_path):
    """Paths must resolve from the modules, not from os.getcwd().

    A systemd unit without WorkingDirectory (or any manual launch from
    elsewhere) previously made every database report as missing.
    """
    from_root = health_monitor.get_database_status()

    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        from_elsewhere = health_monitor.get_database_status()
    finally:
        os.chdir(original)

    assert from_elsewhere == from_root
    assert all(entry["exists"] for entry in from_elsewhere.values())


# --- /health/errors ------------------------------------------------------


def test_error_summary_reports_counts_and_recent_errors(client):
    recent = {"timestamp": datetime.now(), "type": "Sync", "message": "boom"}
    stale = {
        "timestamp": datetime.now() - timedelta(hours=2),
        "type": "Sync",
        "message": "old boom",
    }
    last_error_time = datetime.now()

    with (
        patch.object(health_monitor, "error_count", 7),
        patch.object(health_monitor, "critical_errors", [stale, recent]),
        patch.object(health_monitor, "last_error_time", last_error_time),
    ):
        response = client.get("/health/errors")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total_errors"] == 7
    assert body["critical_errors"] == 2
    assert body["last_error_time"] == last_error_time.isoformat()
    # Only errors inside the restart window count towards a restart.
    assert len(body["recent_critical_errors"]) == 1
    assert body["restart_threshold"] == health_monitor.restart_threshold
    assert body["should_restart"] is False


def test_error_summary_flags_restart_at_threshold(client):
    errors = [
        {"timestamp": datetime.now(), "type": "Sync", "message": f"boom {i}"}
        for i in range(health_monitor.restart_threshold)
    ]

    with (
        patch.object(health_monitor, "error_count", len(errors)),
        patch.object(health_monitor, "critical_errors", errors),
        patch.object(health_monitor, "last_error_time", datetime.now()),
    ):
        response = client.get("/health/errors")

    assert response.status_code == 200
    assert response.get_json()["should_restart"] is True


def test_error_summary_with_no_errors_reports_null_last_error(client):
    with (
        patch.object(health_monitor, "error_count", 0),
        patch.object(health_monitor, "critical_errors", []),
        patch.object(health_monitor, "last_error_time", None),
    ):
        response = client.get("/health/errors")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total_errors"] == 0
    assert body["last_error_time"] is None
    assert body["recent_critical_errors"] == []


def test_error_summary_failure_returns_json_not_html(client):
    with patch.object(
        health_monitor, "_get_recent_critical_errors", side_effect=RuntimeError("bad")
    ):
        response = client.get("/health/errors")

    assert_json_error(response, 500)
    assert "error" in response.get_json()


# --- /health/sync --------------------------------------------------------


def test_sync_status_reports_scheduler_jobs_and_counters(client):
    """Real scheduler state, driven through the public API.

    This endpoint exists because a wedged sync was previously only visible by
    reading the log over SSH, so the per-job counters have to be genuinely
    wired up, not merely present.
    """
    test_scheduler = SyncScheduler(thread_name="test-scheduler")

    def failing_job():
        raise ValueError("google said no")

    test_scheduler.add_job("calendar-sync", lambda: None, interval=300)
    test_scheduler.add_job("chores-sync", failing_job, interval=120)
    # One tick: both jobs are due immediately (run_immediately defaults True).
    test_scheduler.run_due_jobs()

    with (
        patch("src.scheduler.scheduler", test_scheduler),
        patch.object(registry, "tasks", {}),
    ):
        response = client.get("/health/sync")

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"scheduler_running", "jobs", "tasks"}
    # Never started, so the thread is not alive.
    assert body["scheduler_running"] is False

    jobs = {job["name"]: job for job in body["jobs"]}
    assert set(jobs) == {"calendar-sync", "chores-sync"}
    assert jobs["calendar-sync"]["run_count"] == 1
    assert jobs["calendar-sync"]["error_count"] == 0
    assert jobs["calendar-sync"]["last_error"] is None
    assert jobs["calendar-sync"]["interval_seconds"] == 300
    # A job that raises is counted and its reason surfaced, not swallowed.
    assert jobs["chores-sync"]["run_count"] == 0
    assert jobs["chores-sync"]["error_count"] == 1
    assert jobs["chores-sync"]["last_error"] == "google said no"


def test_sync_status_reports_running_scheduler(client):
    """scheduler_running tracks the actual thread, not a flag someone set."""
    test_scheduler = SyncScheduler(thread_name="test-scheduler-live")
    # A long tick so the loop sleeps immediately instead of doing work.
    test_scheduler.start(tick_seconds=60)
    try:
        with (
            patch("src.scheduler.scheduler", test_scheduler),
            patch.object(registry, "tasks", {}),
        ):
            response = client.get("/health/sync")
    finally:
        test_scheduler.stop(timeout=2)

    assert response.status_code == 200
    assert response.get_json()["scheduler_running"] is True


def test_sync_status_reflects_live_task_state(client):
    """Task status comes from the registry the sync code actually writes to."""
    tasks = {
        "calendar.5.2025": {
            "status": COMPLETE,
            "updated": True,
            "events_changed": True,
            "last_update_time": 1_700_000_000.0,
        },
        "tasks": {"status": RUNNING, "updated": False},
    }

    with (
        patch("src.scheduler.scheduler", SyncScheduler()),
        patch.object(registry, "tasks", tasks),
    ):
        response = client.get("/health/sync")

    assert response.status_code == 200
    body = response.get_json()
    assert body["tasks"]["calendar.5.2025"]["status"] == "complete"
    assert body["tasks"]["calendar.5.2025"]["events_changed"] is True
    assert body["tasks"]["tasks"]["status"] == "running"
    assert body["jobs"] == []


def test_sync_status_snapshot_does_not_expose_live_task_dicts(client):
    """The response is built from copies, so serialising cannot race a worker."""
    live_entry = {"status": RUNNING, "updated": False}

    with (
        patch("src.scheduler.scheduler", SyncScheduler()),
        patch.object(registry, "tasks", {"tasks": live_entry}),
    ):
        response = client.get("/health/sync")
        # A worker mutating the entry after the snapshot must not be visible in
        # the already-rendered response.
        live_entry["status"] = COMPLETE

    assert response.get_json()["tasks"]["tasks"]["status"] == "running"


def test_sync_status_failure_returns_json_not_html(client):
    broken = SyncScheduler()
    with (
        patch.object(
            broken, "job_status", side_effect=RuntimeError("scheduler exploded")
        ),
        patch("src.scheduler.scheduler", broken),
    ):
        response = client.get("/health/sync")

    assert_json_error(response, 500)
    assert response.get_json()["status"] == "error"


# --- /health/monitoring/{enable,disable} ---------------------------------


def test_disable_monitoring_flips_the_flag(client, monitoring_flag):
    assert health_monitor.monitoring_enabled is True

    response = client.post("/health/monitoring/disable")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["monitoring_enabled"] is False
    # The reported value matches the real global, not just the JSON literal.
    assert health_monitor.monitoring_enabled is False


def test_enable_monitoring_flips_the_flag(client, monitoring_flag):
    health_monitor.monitoring_enabled = False

    response = client.post("/health/monitoring/enable")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["monitoring_enabled"] is True
    assert health_monitor.monitoring_enabled is True


def test_monitoring_flag_is_restored_between_tests():
    """Guards the fixture itself: the suite must not inherit a disabled monitor."""
    assert health_monitor.monitoring_enabled is True


def test_monitoring_endpoints_reject_get(client, monitoring_flag):
    """State-changing routes are POST-only, so a crawler cannot flip them."""
    assert client.get("/health/monitoring/disable").status_code == 405
    assert client.get("/health/monitoring/enable").status_code == 405
    assert health_monitor.monitoring_enabled is True


def test_enable_monitoring_failure_returns_json_not_html(client, monitoring_flag):
    with patch.object(
        health_monitor, "enable_monitoring", side_effect=RuntimeError("nope")
    ):
        response = client.post("/health/monitoring/enable")

    assert_json_error(response, 500)
    assert "error" in response.get_json()


def test_disable_monitoring_failure_returns_json_not_html(client, monitoring_flag):
    with patch.object(
        health_monitor, "disable_monitoring", side_effect=RuntimeError("nope")
    ):
        response = client.post("/health/monitoring/disable")

    assert_json_error(response, 500)
    assert "error" in response.get_json()
