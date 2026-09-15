"""Runs the real upgrade.sh against a throwaway git repository.

systemctl, uv, npm and curl are replaced by stub scripts on PATH that record
their arguments, so each scenario takes well under a second and never touches
the machine's services or package caches. What is exercised is the script's
own logic: preflight ordering, lockfile restoration, rollback, and status
reporting.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UPGRADE_SH = REPO_ROOT / "upgrade.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="needs bash and git",
)

STUB = """#!/bin/bash
echo "{name} $*" >> "$STUB_LOG"
{body}
exit 0
"""

STUBS = {
    "systemctl": 'case "$1" in is-active|list-unit-files) exit 0;; esac',
    "uv": "",
    # Fails the frontend build when the checked-out VERSION matches FAIL_BUILD_ON.
    "npm": (
        'if [ "$1" = "run" ] && [ -n "${FAIL_BUILD_ON:-}" ] '
        '&& [ "$(cat ../VERSION)" = "$FAIL_BUILD_ON" ]; then '
        'echo "simulated build failure" >&2; exit 1; fi'
    ),
    "curl": "",
    "sudo": 'exec "$@"',
}


def git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    ).stdout.strip()


@pytest.fixture
def install(tmp_path):
    """An installed checkout on 0.9.0 whose origin has a v1.0.0 release."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    app = tmp_path / "app"
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    for d in (seed, home, bin_dir):
        d.mkdir()

    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(seed, "init", "-q", "-b", "main")
    (seed / "frontend").mkdir()
    shutil.copy(UPGRADE_SH, seed / "upgrade.sh")
    (seed / "VERSION").write_text("0.9.0\n")
    (seed / "uv.lock").write_text("lock 0.9.0\n")
    (seed / "frontend" / "package-lock.json").write_text("{}\n")
    (seed / "README.md").write_text("readme\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "0.9.0")
    old = git(seed, "rev-parse", "HEAD")
    (seed / "VERSION").write_text("1.0.0\n")
    (seed / "uv.lock").write_text("lock 1.0.0\n")
    git(seed, "commit", "-q", "-am", "1.0.0")
    git(seed, "tag", "v1.0.0")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main", "--tags")

    git(tmp_path, "clone", "-q", str(origin), str(app))
    git(app, "checkout", "-q", "-b", "installed", old)

    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text(STUB.format(name=name, body=body))
        stub.chmod(0o755)

    log = tmp_path / "stub.log"
    log.touch()
    status = tmp_path / "status.json"

    def run(*args, **env):
        result = subprocess.run(
            [
                "bash",
                str(app / "upgrade.sh"),
                "--yes",
                "--status-file",
                str(status),
                *args,
            ],
            cwd=app,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HOME": str(home),
                "STUB_LOG": str(log),
                **env,
            },
        )
        result.calls = log.read_text().splitlines()
        result.status = json.loads(status.read_text()) if status.exists() else None
        return result

    run.app = app
    return run


def service_calls(result):
    return [c for c in result.calls if c.startswith("systemctl ")]


def test_upgrades_to_the_latest_release(install):
    result = install()
    assert result.returncode == 0, result.stdout + result.stderr
    assert (install.app / "VERSION").read_text().strip() == "1.0.0"
    assert result.status["state"] == "done"
    assert "uv sync --frozen --no-dev" in result.calls
    assert "npm run build" in result.calls
    assert service_calls(result) == [
        "systemctl list-unit-files family-calendar.service",
        "systemctl is-active --quiet family-calendar",
        "systemctl stop family-calendar",
        "systemctl start family-calendar",
    ]


def test_rewritten_lockfiles_are_restored_not_fatal(install):
    """uv or npm rewriting a lockfile on the Pi must not block the checkout."""
    (install.app / "uv.lock").write_text("rewritten by a newer uv\n")
    (install.app / "frontend" / "package-lock.json").write_text('{"x": 1}\n')
    result = install()
    assert result.returncode == 0, result.stdout + result.stderr
    assert (install.app / "VERSION").read_text().strip() == "1.0.0"
    assert (install.app / "uv.lock").read_text() == "lock 1.0.0\n"


def test_local_edits_refuse_before_the_service_is_stopped(install):
    (install.app / "README.md").write_text("someone edited this on the Pi\n")
    result = install()
    assert result.returncode != 0
    assert "README.md" in result.stderr
    assert result.status["state"] == "error"
    assert "Local changes" in result.status["message"]
    assert (install.app / "VERSION").read_text().strip() == "0.9.0"
    assert "systemctl stop family-calendar" not in result.calls
    assert not [c for c in result.calls if c.startswith(("uv ", "npm "))]


def test_failed_build_rolls_back_and_restarts_the_old_version(install):
    result = install(FAIL_BUILD_ON="1.0.0")
    assert result.returncode != 0
    assert "simulated build failure" in result.stderr
    assert result.status == {
        "state": "error",
        "message": "Frontend build failed.",
        "updated_at": result.status["updated_at"],
    }
    assert git(install.app, "rev-parse", "--abbrev-ref", "HEAD") == "installed"
    assert (install.app / "VERSION").read_text().strip() == "0.9.0"
    assert git(install.app, "status", "--porcelain", "--untracked-files=no") == ""
    # Rebuilt the old version, then put the service back.
    assert result.calls.count("npm run build") == 2
    assert service_calls(result)[-1] == "systemctl restart family-calendar"


def test_unknown_release_refuses_before_the_service_is_stopped(install):
    result = install("--tag", "v9.9.9")
    assert result.returncode != 0
    assert "v9.9.9 does not exist" in result.status["message"]
    assert "systemctl stop family-calendar" not in result.calls


def test_already_on_the_release_is_a_no_op(install):
    git(install.app, "checkout", "-q", "v1.0.0")
    result = install()
    assert result.returncode == 0
    assert result.status["state"] == "done"
    assert "Already up to date" in result.status["message"]
    assert "systemctl stop family-calendar" not in result.calls
