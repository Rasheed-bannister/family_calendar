"""Tests for src/version.py - Version management and upgrade functionality."""

import json
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from src import version as version_module
from src.version import (
    _is_newer,
    _set_status,
    check_for_update,
    get_current_version,
    get_upgrade_status,
    start_upgrade,
)

# --- get_current_version ---


class TestGetCurrentVersion:
    def test_reads_version_file(self, tmp_path):
        (tmp_path / "VERSION").write_text("1.2.3\n")
        with patch("src.version.PROJECT_ROOT", tmp_path):
            assert get_current_version() == "1.2.3"

    def test_returns_unknown_when_file_missing(self, tmp_path):
        with patch("src.version.PROJECT_ROOT", tmp_path):
            assert get_current_version() == "unknown"

    def test_strips_whitespace(self, tmp_path):
        """VERSION file content should be stripped of whitespace."""
        (tmp_path / "VERSION").write_text("  2.0.0  \n")
        with patch("src.version.PROJECT_ROOT", tmp_path):
            assert get_current_version() == "2.0.0"


# --- _is_newer ---


class TestIsNewer:
    def test_newer_major(self):
        assert _is_newer("2.0.0", "1.0.0") is True

    def test_newer_minor(self):
        assert _is_newer("1.1.0", "1.0.0") is True

    def test_newer_patch(self):
        assert _is_newer("1.0.1", "1.0.0") is True

    def test_same_version(self):
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_older_version(self):
        assert _is_newer("1.0.0", "2.0.0") is False

    def test_older_minor(self):
        assert _is_newer("1.0.0", "1.1.0") is False

    def test_invalid_latest(self):
        assert _is_newer("abc", "1.0.0") is False

    def test_invalid_current(self):
        assert _is_newer("1.0.0", "abc") is False

    def test_empty_strings(self):
        assert _is_newer("", "") is False

    def test_none_values(self):
        assert _is_newer(None, "1.0.0") is False


# --- check_for_update ---


class TestCheckForUpdate:
    def test_returns_update_available(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/test/releases/v99.0.0",
        }
        with patch("src.version.requests.get", return_value=mock_response):
            result = check_for_update()
        assert result["update_available"] is True
        assert result["latest_version"] == "99.0.0"
        assert result["release_url"] == "https://github.com/test/releases/v99.0.0"

    def test_returns_no_update_when_current(self):
        current = get_current_version()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": f"v{current}",
            "html_url": "https://github.com/test/releases",
        }
        with patch("src.version.requests.get", return_value=mock_response):
            result = check_for_update()
        assert result["update_available"] is False
        assert result["current_version"] == current

    def test_returns_no_update_when_older(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/test/releases/v0.0.1",
        }
        with patch("src.version.requests.get", return_value=mock_response):
            result = check_for_update()
        assert result["update_available"] is False

    def test_handles_api_failure(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        with patch("src.version.requests.get", return_value=mock_response):
            result = check_for_update()
        assert result["update_available"] is False
        assert result["latest_version"] is None

    def test_handles_network_error(self):
        with patch(
            "src.version.requests.get", side_effect=ConnectionError("no internet")
        ):
            result = check_for_update()
        assert result["update_available"] is False
        assert result["current_version"] is not None

    def test_handles_empty_tag(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tag_name": "", "html_url": ""}
        with patch("src.version.requests.get", return_value=mock_response):
            result = check_for_update()
        assert result["update_available"] is False

    def test_strips_v_prefix_from_tag(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
        }
        with patch("src.version.requests.get", return_value=mock_response):
            result = check_for_update()
        assert result["latest_version"] == "2.0.0"


# --- get_upgrade_status / start_upgrade ---


@pytest.fixture
def status_file(tmp_path):
    """Point the module at a throwaway status file and reset launcher state."""
    path = tmp_path / ".upgrade-status.json"
    with patch("src.version.STATUS_FILE", path):
        version_module._upgrade_status.update(
            {"state": "idle", "message": "", "updated_at": 0.0}
        )
        yield path


def write_script_status(path, state, message, age_seconds=0.0):
    path.write_text(
        json.dumps(
            {
                "state": state,
                "message": message,
                "updated_at": time.time() - age_seconds,
            }
        )
    )


class TestUpgradeStatus:
    def test_initial_status_is_idle(self, status_file):
        assert get_upgrade_status() == {"state": "idle", "message": ""}

    def test_script_status_file_wins_when_newer(self, status_file):
        _set_status("running", "Starting upgrade to v2.0.0...")
        write_script_status(status_file, "error", "Frontend build failed.")
        assert get_upgrade_status() == {
            "state": "error",
            "message": "Frontend build failed.",
        }

    def test_launcher_status_wins_over_an_older_file(self, status_file):
        write_script_status(status_file, "done", "Upgraded to 1.0.0", age_seconds=60)
        _set_status("error", "Could not start the upgrade: boom")
        assert get_upgrade_status()["state"] == "error"

    def test_corrupt_status_file_is_ignored(self, status_file):
        status_file.write_text("{not json")
        _set_status("running", "Starting")
        assert get_upgrade_status() == {"state": "running", "message": "Starting"}

    def test_rejects_duplicate_upgrade_while_script_runs(self, status_file):
        write_script_status(status_file, "running", "Building the frontend ...")
        with patch("src.version._launch_upgrade") as launch:
            result = start_upgrade("v1.0.0")
        assert result["success"] is False
        assert "already in progress" in result["message"]
        launch.assert_not_called()

    def test_stale_running_status_does_not_block_forever(self, status_file):
        write_script_status(
            status_file,
            "running",
            "killed mid-way",
            age_seconds=version_module.STALE_RUNNING_SECONDS + 1,
        )
        with patch("src.version._launch_upgrade", return_value="process"):
            assert start_upgrade("v1.0.0")["success"] is True

    def test_start_clears_previous_status_file(self, status_file):
        write_script_status(status_file, "error", "old failure", age_seconds=10)
        with patch("src.version._launch_upgrade", return_value="systemd"):
            result = start_upgrade("v2.0.0")
        assert result == {"success": True, "message": "Upgrade to v2.0.0 started"}
        assert not status_file.exists()
        assert get_upgrade_status()["state"] == "running"

    def test_launch_failure_is_logged_but_not_returned(self, status_file, caplog):
        with patch(
            "src.version._launch_upgrade", side_effect=RuntimeError("polkit said no")
        ):
            result = start_upgrade("v2.0.0")
        assert result["success"] is False
        assert "polkit said no" not in result["message"]
        assert "service log" in result["message"]
        assert get_upgrade_status()["state"] == "error"
        assert "polkit said no" not in get_upgrade_status()["message"]
        assert "polkit said no" in caplog.text

    @pytest.mark.parametrize(
        "tag", ["", "1.0.0", "v1.0", "v1.0.0\nforged", "v1.0.0; rm"]
    )
    def test_rejects_malformed_tags_before_launching(self, status_file, tag):
        with patch("src.version._launch_upgrade") as launch:
            result = start_upgrade(tag)
        assert result["success"] is False
        assert "Invalid tag" in result["message"]
        launch.assert_not_called()


# --- _launch_upgrade ---


class TestLaunchUpgrade:
    def test_uses_the_systemd_unit_when_installed(self):
        with (
            patch("src.version._upgrade_unit_installed", return_value=True),
            patch("src.version.shutil.which", return_value="/usr/bin/systemctl"),
            patch("src.version.subprocess.run") as run,
            patch("src.version.subprocess.Popen") as popen,
        ):
            assert version_module._launch_upgrade("v1.2.3") == "systemd"
        argv = run.call_args.args[0]
        assert argv == [
            "/usr/bin/systemctl",
            "start",
            "--no-block",
            "family-calendar-upgrade@v1.2.3.service",
        ]
        popen.assert_not_called()

    def test_systemctl_failure_explains_the_fix(self):
        error = subprocess.CalledProcessError(1, "systemctl", stderr="Access denied")
        with (
            patch("src.version._upgrade_unit_installed", return_value=True),
            patch("src.version.subprocess.run", side_effect=error),
        ):
            with pytest.raises(
                RuntimeError, match="Access denied.*deploy_raspberry_pi"
            ):
                version_module._launch_upgrade("v1.2.3")

    def test_falls_back_to_a_detached_script(self, status_file):
        with (
            patch("src.version._upgrade_unit_installed", return_value=False),
            patch("src.version.subprocess.Popen") as popen,
        ):
            assert version_module._launch_upgrade("v1.2.3") == "process"
        argv = popen.call_args.args[0]
        assert argv[0] == "bash"
        assert argv[1].endswith("upgrade.sh")
        assert argv[2:] == [
            "--yes",
            "--tag",
            "v1.2.3",
            "--status-file",
            str(status_file),
        ]
        # Its own session, so it is not tied to the web server's process group.
        assert popen.call_args.kwargs["start_new_session"] is True

    def test_missing_script_is_an_error(self, tmp_path):
        with (
            patch("src.version._upgrade_unit_installed", return_value=False),
            patch("src.version.UPGRADE_SCRIPT", tmp_path / "nope.sh"),
        ):
            with pytest.raises(RuntimeError, match="not found"):
                version_module._launch_upgrade("v1.2.3")

    def test_unit_detection_without_systemctl(self):
        with patch("src.version.shutil.which", return_value=None):
            assert version_module._upgrade_unit_installed() is False

    def test_unit_detection_uses_systemctl_cat(self):
        with (
            patch("src.version.shutil.which", return_value="/usr/bin/systemctl"),
            patch(
                "src.version.subprocess.run",
                return_value=MagicMock(returncode=0),
            ) as run,
        ):
            assert version_module._upgrade_unit_installed() is True
        assert run.call_args.args[0] == [
            "/usr/bin/systemctl",
            "cat",
            "family-calendar-upgrade@.service",
        ]


# --- API endpoint tests ---


class TestVersionAPI:
    @pytest.fixture
    def client(self):
        from src.main import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    def test_version_endpoint(self, client):
        response = client.get("/api/version")
        assert response.status_code == 200
        data = response.get_json()
        assert "current_version" in data

    def test_version_check_update(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v99.0.0",
            "html_url": "https://example.com",
        }
        with patch("src.version.requests.get", return_value=mock_response):
            response = client.get("/api/version?check_update=true")
        assert response.status_code == 200
        data = response.get_json()
        assert "update_available" in data
        assert data["update_available"] is True

    def test_upgrade_endpoint_requires_tag(self, client):
        response = client.post(
            "/api/upgrade",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False

    def test_upgrade_rejects_invalid_tag_format(self, client):
        response = client.post(
            "/api/upgrade",
            json={"tag": "not-a-tag"},
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["success"] is False
        assert "Invalid tag format" in data["message"]

    def test_upgrade_status_is_localhost_only(self, client, status_file):
        response = client.get(
            "/api/upgrade/status", environ_base={"REMOTE_ADDR": "192.168.1.50"}
        )
        assert response.status_code == 403
        assert response.get_json()["state"] == "unavailable"

    def test_upgrade_status_endpoint(self, client, status_file):
        response = client.get("/api/upgrade/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["state"] == "idle"
