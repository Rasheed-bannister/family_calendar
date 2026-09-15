"""Tests for src/display/backlight.py."""

import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from src.display import backlight as bl


class Cfg:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def make_sysfs(tmp_path, max_brightness=255, name="rpi_backlight"):
    device = tmp_path / name
    device.mkdir()
    (device / "max_brightness").write_text(f"{max_brightness}\n")
    (device / "brightness").write_text(f"{max_brightness}\n")
    return device


class TestNullBacklight:
    def test_is_unavailable_and_inert(self):
        b = bl.NullBacklight()
        assert b.available is False
        assert b.set_brightness(0.5) is False
        assert b.describe() == {"backend": "none", "available": False}


class TestSysfsBacklight:
    def test_writes_scaled_value(self, tmp_path):
        device = make_sysfs(tmp_path, 255)
        b = bl.SysfsBacklight(device)
        assert b.available is True
        assert b.set_brightness(0.5) is True
        assert (device / "brightness").read_text() == "128\n"

    def test_never_writes_zero(self, tmp_path):
        device = make_sysfs(tmp_path, 100)
        b = bl.SysfsBacklight(device)
        b.set_brightness(0.0)
        assert int((device / "brightness").read_text()) >= 1

    def test_clamps_above_one(self, tmp_path):
        device = make_sysfs(tmp_path, 100)
        bl.SysfsBacklight(device).set_brightness(5.0)
        assert (device / "brightness").read_text() == "100\n"

    def test_unreadable_max_is_unavailable(self, tmp_path):
        device = tmp_path / "broken"
        device.mkdir()
        (device / "brightness").write_text("1\n")
        b = bl.SysfsBacklight(device)
        assert b.available is False
        assert b.set_brightness(0.5) is False

    def test_write_failure_is_reported_once(self, tmp_path, caplog):
        device = make_sysfs(tmp_path, 100)
        b = bl.SysfsBacklight(device)
        with patch.object(
            type(device / "brightness"),
            "write_text",
            side_effect=PermissionError("denied"),
        ):
            with caplog.at_level("ERROR"):
                assert b.set_brightness(0.5) is False
                assert b.set_brightness(0.4) is False
        assert caplog.text.count("Cannot write backlight") == 1
        assert "denied" in b.describe()["error"]

    def test_describe(self, tmp_path):
        device = make_sysfs(tmp_path, 255)
        info = bl.SysfsBacklight(device).describe()
        assert info["backend"] == "sysfs"
        assert info["available"] is True
        assert info["device"] == str(device)
        assert info["max_brightness"] == 255


class TestDdcutilBacklight:
    @pytest.fixture(autouse=True)
    def no_worker_thread(self):
        """Run the drain only inline, where the test calls it.

        set_brightness() normally starts a background thread. Left running,
        it races the inline _drain() for the pending value; when it wins, the
        inline call has nothing to do and the assertion can run before the
        thread records its result (seen under the slower coverage run in CI).
        """
        with patch.object(bl.threading, "Thread"):
            yield

    def test_unavailable_without_binary(self):
        with patch.object(bl.shutil, "which", return_value=None):
            b = bl.DdcutilBacklight()
            assert b.available is False
            assert b.set_brightness(0.5) is False

    def test_runs_setvcp_with_percent(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"):
            with patch.object(bl.subprocess, "run", side_effect=fake_run):
                b = bl.DdcutilBacklight(display="2")
                assert b.set_brightness(0.25) is True
                b._drain()  # run the worker inline
        assert calls[-1][:4] == ["ddcutil", "setvcp", "10", "25"]
        assert "--display" in calls[-1] and "2" in calls[-1]

    def test_failure_is_recorded(self):
        with patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"):
            with patch.object(
                bl.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "ddcutil"),
            ):
                b = bl.DdcutilBacklight()
                b.set_brightness(0.5)
                b._drain()
        assert b.describe()["error"]


class TestDdcutilWorker:
    """One worker at a time, and the newest level is always written last."""

    def test_burst_before_the_worker_runs_starts_one_worker(self):
        calls = []
        with (
            patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"),
            patch.object(
                bl.subprocess,
                "run",
                side_effect=lambda argv, **kw: calls.append(argv[3]),
            ),
            patch.object(bl.threading, "Thread") as thread,
        ):
            b = bl.DdcutilBacklight()
            b.set_brightness(0.2)
            b.set_brightness(0.5)
            b.set_brightness(0.9)
            assert thread.call_count == 1
            b._drain()
        assert calls == ["90"]

    def test_a_new_worker_starts_after_the_previous_one_finished(self):
        with (
            patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"),
            patch.object(bl.subprocess, "run"),
            patch.object(bl.threading, "Thread") as thread,
        ):
            b = bl.DdcutilBacklight()
            b.set_brightness(0.2)
            b._drain()
            b.set_brightness(0.4)
            assert thread.call_count == 2

    def test_thread_start_failure_does_not_wedge_the_driver(self):
        with (
            patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"),
            patch.object(bl.threading, "Thread") as thread,
        ):
            thread.return_value.start.side_effect = RuntimeError("can't start")
            b = bl.DdcutilBacklight()
            with pytest.raises(RuntimeError):
                b.set_brightness(0.2)
            thread.return_value.start.side_effect = None
            b.set_brightness(0.3)
            assert thread.call_count == 2

    def test_request_during_a_slow_call_is_written_after_it_by_the_same_worker(
        self,
    ):
        """Real threads: hold the first ddcutil call open while newer levels arrive."""
        inside_first_call = threading.Event()
        release_first_call = threading.Event()
        calls = []
        threads = set()
        lock = threading.Lock()

        def fake_run(argv, **kwargs):
            with lock:
                calls.append(argv[3])
                threads.add(threading.get_ident())
                first = len(calls) == 1
            if first:
                inside_first_call.set()
                assert release_first_call.wait(5)
            return subprocess.CompletedProcess(argv, 0)

        with (
            patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"),
            patch.object(bl.subprocess, "run", side_effect=fake_run),
        ):
            b = bl.DdcutilBacklight()
            b.set_brightness(0.2)
            assert inside_first_call.wait(5)
            b.set_brightness(0.5)  # dim...
            b.set_brightness(0.9)  # ...then wake: this must be the last write
            release_first_call.set()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with b._lock:
                    if not b._worker_active:
                        break
                time.sleep(0.01)

        assert calls == ["20", "90"]
        assert len(threads) == 1
        assert b._worker_active is False


class TestCreateBacklight:
    def test_auto_prefers_sysfs(self, tmp_path):
        make_sysfs(tmp_path)
        with patch.object(bl, "SYSFS_ROOT", tmp_path):
            b = bl.create_backlight(Cfg())
        assert isinstance(b, bl.SysfsBacklight)

    def test_auto_falls_back_to_ddcutil(self, tmp_path):
        with patch.object(bl, "SYSFS_ROOT", tmp_path / "missing"):
            with patch.object(bl.shutil, "which", return_value="/usr/bin/ddcutil"):
                b = bl.create_backlight(Cfg())
        assert isinstance(b, bl.DdcutilBacklight)

    def test_auto_falls_back_to_none(self, tmp_path):
        with patch.object(bl, "SYSFS_ROOT", tmp_path / "missing"):
            with patch.object(bl.shutil, "which", return_value=None):
                b = bl.create_backlight(Cfg())
        assert isinstance(b, bl.NullBacklight)

    def test_explicit_sysfs_device(self, tmp_path):
        make_sysfs(tmp_path, name="panel")
        make_sysfs(tmp_path, name="other")
        cfg = Cfg(
            **{
                "display.backlight.backend": "sysfs",
                "display.backlight.device": "panel",
            }
        )
        with patch.object(bl, "SYSFS_ROOT", tmp_path):
            b = bl.create_backlight(cfg)
        assert b.describe()["device"].endswith("panel")

    def test_explicit_sysfs_without_device_is_none(self, tmp_path, caplog):
        cfg = Cfg(**{"display.backlight.backend": "sysfs"})
        with patch.object(bl, "SYSFS_ROOT", tmp_path):
            with caplog.at_level("ERROR"):
                b = bl.create_backlight(cfg)
        assert isinstance(b, bl.NullBacklight)
        assert "no device found" in caplog.text

    def test_explicit_none(self, tmp_path):
        make_sysfs(tmp_path)
        with patch.object(bl, "SYSFS_ROOT", tmp_path):
            b = bl.create_backlight(Cfg(**{"display.backlight.backend": "none"}))
        assert isinstance(b, bl.NullBacklight)

    @pytest.mark.parametrize("backend", ["bogus", "SYSFS"])
    def test_backend_names_are_case_insensitive_or_rejected(self, tmp_path, backend):
        make_sysfs(tmp_path)
        with patch.object(bl, "SYSFS_ROOT", tmp_path):
            b = bl.create_backlight(Cfg(**{"display.backlight.backend": backend}))
        if backend == "SYSFS":
            assert isinstance(b, bl.SysfsBacklight)
        else:
            assert isinstance(b, bl.NullBacklight)
