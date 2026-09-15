"""Version checks and the in-app upgrade launcher.

The upgrade itself is ``upgrade.sh``; this module only starts it and reports
its progress, so the terminal and the settings panel run exactly the same
procedure (preflight, backup, checkout, rebuild, restart, rollback on failure).
"""

import json
import logging
import re
import shutil
import subprocess  # nosec B404 - fixed argv only
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from src.log_safe import log_safe

logger = logging.getLogger(__name__)

# GitHub repository for update checks
GITHUB_REPO = "Rasheed-bannister/family_calendar"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

PROJECT_ROOT = Path(__file__).parent.parent
UPGRADE_SCRIPT = PROJECT_ROOT / "upgrade.sh"

# Written by upgrade.sh (--status-file) so progress survives the service being
# stopped and restarted part-way through. Gitignored.
STATUS_FILE = PROJECT_ROOT / ".upgrade-status.json"

# Installed by deploy_raspberry_pi.sh. The service runs sandboxed
# (NoNewPrivileges, read-only home), which blocks sudo and the uv/npm caches,
# and stopping the service kills any child process it spawned. So the upgrade
# runs in its own unit, started over D-Bus; a polkit rule lets the service
# user do that without sudo.
UPGRADE_UNIT_TEMPLATE = "family-calendar-upgrade@.service"

# Release tags accepted for upgrades. Also enforced here, not only in the
# route, because the tag becomes part of a systemd unit name.
TAG_PATTERN = re.compile(r"v\d+\.\d+\.\d+")

# A "running" status older than this is treated as abandoned (the upgrade was
# killed), so it cannot block every future upgrade.
STALE_RUNNING_SECONDS = 30 * 60

# Launch-phase state, before upgrade.sh has written its status file.
_upgrade_status: dict = {"state": "idle", "message": "", "updated_at": 0.0}
_upgrade_lock = threading.Lock()


def get_current_version() -> str:
    """Read the current version from the VERSION file."""
    version_file = PROJECT_ROOT / "VERSION"
    try:
        return version_file.read_text().strip()
    except FileNotFoundError:
        return "unknown"


def check_for_update() -> dict:
    """Check GitHub releases for a newer version.

    Returns:
        dict with keys: update_available (bool), latest_version (str|None),
        current_version (str), release_url (str|None)
    """
    current = get_current_version()
    result = {
        "update_available": False,
        "latest_version": None,
        "current_version": current,
        "release_url": None,
    }

    try:
        resp = requests.get(GITHUB_API_URL, timeout=10)
        if resp.status_code != 200:
            return result

        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_version = latest_tag.lstrip("v")

        result["latest_version"] = latest_version
        result["release_url"] = data.get("html_url")

        if latest_version and latest_version != current:
            result["update_available"] = _is_newer(latest_version, current)

    except Exception:
        logger.debug("Could not check for updates", exc_info=True)

    return result


# --- upgrade status ---------------------------------------------------------


def _read_status_file() -> Optional[dict]:
    try:
        data = json.loads(STATUS_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "state" not in data:
        return None
    return data


def _set_status(state: str, message: str) -> None:
    with _upgrade_lock:
        _upgrade_status["state"] = state
        _upgrade_status["message"] = message
        _upgrade_status["updated_at"] = time.time()


def get_upgrade_status() -> dict:
    """Current upgrade state: whichever of the launcher and the script spoke last."""
    with _upgrade_lock:
        status = dict(_upgrade_status)
    from_script = _read_status_file()
    if from_script and float(from_script.get("updated_at", 0)) >= float(
        status.get("updated_at", 0)
    ):
        status = from_script
    return {
        "state": status.get("state", "idle"),
        "message": status.get("message", ""),
    }


def _is_fresh_running(status: Optional[dict]) -> bool:
    return bool(
        status
        and status.get("state") == "running"
        and time.time() - float(status.get("updated_at", 0)) < STALE_RUNNING_SECONDS
    )


def _upgrade_in_progress() -> bool:
    with _upgrade_lock:
        launcher = dict(_upgrade_status)
    return _is_fresh_running(launcher) or _is_fresh_running(_read_status_file())


# --- launching --------------------------------------------------------------


def start_upgrade(target_tag: str) -> dict:
    """Start upgrade.sh for ``target_tag`` outside this process.

    Returns immediately. Progress comes from :func:`get_upgrade_status`; the
    script stops and restarts the service itself.
    """
    if not TAG_PATTERN.fullmatch(target_tag or ""):
        return {"success": False, "message": "Invalid tag format (expected vX.Y.Z)"}
    if _upgrade_in_progress():
        return {"success": False, "message": "Upgrade already in progress"}

    _set_status("running", f"Starting upgrade to {target_tag}...")
    try:
        STATUS_FILE.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not clear %s", STATUS_FILE, exc_info=True)

    try:
        how = _launch_upgrade(target_tag)
    except Exception:
        # The exception can carry systemctl's stderr; it goes to the log, and
        # the caller gets a fixed message.
        logger.exception("Could not start the upgrade to %s", log_safe(target_tag))
        message = "Could not start the upgrade. See the family-calendar service log."
        _set_status("error", message)
        return {"success": False, "message": message}

    logger.info("Upgrade to %s started via %s", log_safe(target_tag), how)
    return {"success": True, "message": f"Upgrade to {target_tag} started"}


def _upgrade_unit_installed() -> bool:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603
            [systemctl, "cat", UPGRADE_UNIT_TEMPLATE],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _launch_upgrade(target_tag: str) -> str:
    """Start upgrade.sh and return how: ``"systemd"`` or ``"process"``."""
    if _upgrade_unit_installed():
        unit = UPGRADE_UNIT_TEMPLATE.replace("@.", f"@{target_tag}.")
        try:
            subprocess.run(  # noqa: S603  # nosec B603
                [shutil.which("systemctl") or "systemctl", "start", "--no-block", unit],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or e.stdout or "").strip() or f"exit {e.returncode}"
            raise RuntimeError(
                f"systemctl start {unit} failed ({detail}). Re-run "
                "deploy_raspberry_pi.sh to install the upgrade permissions."
            ) from e
        return "systemd"

    # No upgrade unit (a development machine, or an install that predates it):
    # run the script as a detached process in its own session.
    if not UPGRADE_SCRIPT.is_file():
        raise RuntimeError(f"{UPGRADE_SCRIPT} not found")
    subprocess.Popen(  # noqa: S603  # nosec B603 B607
        [
            "bash",
            str(UPGRADE_SCRIPT),
            "--yes",
            "--tag",
            target_tag,
            "--status-file",
            str(STATUS_FILE),
        ],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return "process"


def _is_newer(latest: str, current: str) -> bool:
    """Compare semver strings. Returns True if latest > current."""
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False
