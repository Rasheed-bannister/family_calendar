"""Version management for Family Calendar application."""

import logging
import subprocess
import threading
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# GitHub repository for update checks
GITHUB_REPO = "Rasheed-bannister/family_calendar"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Upgrade state (in-memory, reset on restart)
_upgrade_status = {"state": "idle", "message": ""}
_upgrade_lock = threading.Lock()


def get_current_version() -> str:
    """Read the current version from the VERSION file."""
    version_file = Path(__file__).parent.parent / "VERSION"
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


def get_upgrade_status() -> dict:
    """Return current upgrade status."""
    with _upgrade_lock:
        return dict(_upgrade_status)


def start_upgrade(target_tag: str) -> dict:
    """Start an upgrade to the given tag in a background thread.

    Returns immediately with status. The upgrade runs asynchronously.
    After completion, the service should be restarted externally
    (systemd will auto-restart if configured).
    """
    with _upgrade_lock:
        if _upgrade_status["state"] == "running":
            return {"success": False, "message": "Upgrade already in progress"}
        _upgrade_status["state"] = "running"
        _upgrade_status["message"] = f"Upgrading to {target_tag}..."

    thread = threading.Thread(target=_run_upgrade, args=(target_tag,), daemon=True)
    thread.start()
    return {"success": True, "message": f"Upgrade to {target_tag} started"}


def _run_upgrade(target_tag: str) -> None:
    """Execute the upgrade steps in a background thread."""
    project_root = Path(__file__).parent.parent

    try:
        # Step 1: Fetch latest tags
        _set_status("running", "Fetching latest releases...")
        _run_cmd(["git", "fetch", "--tags", "--force"], cwd=project_root)

        # Step 2: Discard any local changes to tracked files so checkout succeeds.
        # User data (config.json, credentials, databases, photos) is gitignored
        # and unaffected. Tracked files should always match the release.
        _run_cmd(["git", "checkout", "--", "."], cwd=project_root)

        # Step 3: Checkout the target tag
        _set_status("running", f"Checking out {target_tag}...")
        _run_cmd(["git", "checkout", target_tag], cwd=project_root)

        # Step 4: Ensure system build dependencies are available (Pi only)
        import platform
        import shutil

        if platform.machine() == "aarch64" and not shutil.which("swig"):
            _set_status("running", "Installing system build dependencies...")
            _run_cmd(
                ["sudo", "-n", "apt-get", "install", "-y", "swig", "liblgpio-dev"],
                cwd=project_root,
            )

        # Step 5: Install dependencies into the project's venv
        _set_status("running", "Installing dependencies...")

        venv_python = project_root / ".venv" / "bin" / "python"
        if shutil.which("uv"):
            # Point uv at the project's venv Python so it doesn't use system Python
            _run_cmd(
                ["uv", "sync", "--python", str(venv_python)],
                cwd=project_root,
            )
        elif venv_python.exists():
            _run_cmd(
                [str(venv_python), "-m", "pip", "install", "-e", "."],
                cwd=project_root,
            )
        else:
            raise RuntimeError(
                "No package manager found. Install uv or create a virtualenv."
            )

        _set_status("restarting", "Upgrade complete. Restarting service...")

        # Step 4: Restart via systemd (if available)
        # Use a short delay so the status response can be sent first
        try:
            subprocess.Popen(  # noqa: S603
                ["bash", "-c", "sleep 2 && sudo -n systemctl restart family-calendar"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            # Not running under systemd — caller will need to restart manually
            _set_status(
                "done",
                "Upgrade complete. Please restart the application manually.",
            )

    except subprocess.CalledProcessError as e:
        logger.error("Upgrade failed: %s", e.stderr)
        _set_status("error", f"Upgrade failed: {e.stderr or str(e)}")
    except Exception as e:
        logger.error("Upgrade failed: %s", e)
        _set_status("error", f"Upgrade failed: {e}")


def _run_cmd(cmd: list[str], cwd: Path) -> str:
    """Run a subprocess command, raising on failure."""
    result = subprocess.run(  # noqa: S603
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    return result.stdout


def _set_status(state: str, message: str) -> None:
    with _upgrade_lock:
        _upgrade_status["state"] = state
        _upgrade_status["message"] = message


def _is_newer(latest: str, current: str) -> bool:
    """Compare semver strings. Returns True if latest > current."""
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
        return latest_parts > current_parts
    except (ValueError, AttributeError):
        return False
