#!/usr/bin/env python3
"""PIR Sensor Diagnostic Script for Family Calendar.

Run from the project root:
    .venv/bin/python scripts/diagnose_pir.py

Runs the same checks available via the in-app Settings > PIR Sensor diagnostics,
plus an interactive live sensor test that requires a terminal.
"""

import sys
import time

# Ensure project root is importable
sys.path.insert(0, ".")

from src.pir_sensor.diagnostics import run_all_checks  # noqa: E402

# ANSI colors
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
NC = "\033[0m"

PASS = f"{GREEN}PASS{NC}"
FAIL = f"{RED}FAIL{NC}"
WARN = f"{YELLOW}WARN{NC}"
INFO = f"{BLUE}INFO{NC}"


def header(title: str) -> None:
    print(f"\n{BLUE}=== {title} ==={NC}\n")


def row(label: str, ok: bool, detail: str = "") -> None:
    status = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{suffix}")


def info(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{INFO}] {label}{suffix}")


def warn(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{WARN}] {label}{suffix}")


def print_results(data: dict) -> None:
    """Pretty-print the structured diagnostics data."""
    p = data["platform"]
    header("Platform")
    row("Architecture", p["is_arm"], p["machine"])
    if not p["is_arm"]:
        warn("Not running on ARM", "PIR sensor requires Raspberry Pi GPIO")
    info("Board model", p["model"])
    info("Kernel", p["kernel"])
    info("Python", f"{p['python']} ({p['python_executable']})")

    header("GPIO Devices & Permissions")
    g = data["gpio_devices"]
    for chip in g["chips"]:
        row(chip["path"], chip["accessible"], chip.get("error", f"group={chip.get('group')} mode={chip.get('mode')}"))
    if not g["chips"]:
        warn("No /dev/gpiochip* devices found")
    if g["gpiomem"]:
        row("/dev/gpiomem", g["gpiomem_accessible"])
    else:
        info("/dev/gpiomem", "not present (normal on Pi 5)")
    row(f"User '{g['username']}' in gpio group", g["gpio_group"], ", ".join(g["user_groups"]))
    if not g["gpio_group"]:
        print(f"    {YELLOW}Fix: sudo usermod -aG gpio {g['username']} && logout/login{NC}")

    header("Power Supply")
    pw = data["power"]
    if pw["available"]:
        power_ok = not pw["under_voltage_now"] and not pw["under_voltage_occurred"]
        row("Throttle status", power_ok, pw["throttled_raw"])
        for flag in pw.get("flags", []):
            warn("Throttle flag", flag)
        if not power_ok:
            print(f"    {YELLOW}Under-voltage detected! Use a proper 5V/5A power supply.{NC}")
    else:
        info("vcgencmd", "not available (not on Pi or not in video group)")

    header("Python Libraries")
    lib = data["libraries"]
    row("gpiozero", bool(lib["gpiozero"]), f"v{lib['gpiozero']}" if lib["gpiozero"] else "missing")
    row("lgpio", bool(lib["lgpio"]), f"v{lib['lgpio']}" if lib["lgpio"] else "missing")
    if not lib["lgpio"]:
        print(f"    {YELLOW}Fix: sudo apt-get install -y swig liblgpio-dev{NC}")
        print(f"    {YELLOW}     uv sync --reinstall-package lgpio{NC}")
    if lib["pin_factory"]:
        row("Pin factory", True, lib["pin_factory"])
    row("swig", lib["swig_installed"], "installed" if lib["swig_installed"] else "missing")
    row("liblgpio-dev", lib["liblgpio_installed"], "installed" if lib["liblgpio_installed"] else "missing")

    header("Application Config")
    cfg = data["config"]
    if "error" not in cfg:
        row("PIR enabled", cfg["enabled"])
        row("Simulation mode off", not cfg["simulation_mode"])
        info("GPIO pin", str(cfg["pin"]))
        info("Debounce time", f"{cfg['debounce_time']}s")
    else:
        row("Load config", False, cfg["error"])

    header("Sensor State")
    s = data["sensor"]
    row("Initialized", s["status"] == "initialized", s["status"])
    row("Monitoring", s.get("monitoring", False))

    # Issues
    header("Summary")
    issues = data["issues"]
    if issues:
        print(f"  {RED}Issues found:{NC}")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"  {GREEN}All checks passed.{NC} If motion still isn't detected,")
        print("  check wiring and sensor hardware (potentiometer settings, warmup time).")


def test_sensor_live(pin: int) -> None:
    """Interactive live sensor test (CLI only)."""
    header(f"Live Sensor Test (GPIO {pin})")

    try:
        from gpiozero import MotionSensor
    except ImportError:
        row("Import gpiozero", False, "cannot import")
        return

    print(f"  Creating MotionSensor on pin {pin}...")
    try:
        sensor = MotionSensor(pin, queue_len=1, sample_rate=10, threshold=0.5)
    except Exception as e:
        row("Create MotionSensor", False, str(e))
        return

    row("Create MotionSensor", True)

    try:
        raw = sensor.value
        info("Current sensor value", f"{raw} ({'motion' if raw else 'no motion'})")
    except Exception as e:
        warn("Read sensor value", str(e))

    duration = 15
    print(f"\n  Waiting {duration} seconds for motion (wave your hand over the sensor)...\n")

    detected = False
    start = time.time()
    try:
        while time.time() - start < duration:
            if sensor.motion_detected:
                elapsed = time.time() - start
                row("Motion detected", True, f"after {elapsed:.1f}s")
                detected = True
                time.sleep(2)
                still_active = sensor.motion_detected
                info("Sensor still active after 2s", str(still_active))
                break
            time.sleep(0.1)

        if not detected:
            row("Motion detected", False, f"no motion in {duration}s")
            print(f"\n  {YELLOW}Troubleshooting tips:{NC}")
            print(f"  - Verify wiring: VCC->5V (pin 2/4), GND->GND (pin 6), OUT->GPIO {pin} (pin 12)")
            print("  - Check the sensor's potentiometers (sensitivity and delay)")
            print("  - Try adjusting the sensitivity pot clockwise for higher sensitivity")
            print("  - Some PIR sensors need 30-60s warmup after power-on")
            print("  - Try a different GPIO pin to rule out a dead pin")
    except KeyboardInterrupt:
        print("\n  Interrupted by user")
    finally:
        sensor.close()
        info("Sensor closed", "GPIO released")


def main() -> None:
    print(f"\n{BLUE}{'=' * 50}")
    print("  Family Calendar — PIR Sensor Diagnostics")
    print(f"{'=' * 50}{NC}")

    data = run_all_checks()
    print_results(data)

    # Live test (CLI only, requires terminal + Pi hardware)
    p = data["platform"]
    lib = data["libraries"]
    pin = data["config"].get("pin", 18)

    if p["is_arm"] and lib.get("gpiozero") and lib.get("lgpio"):
        print(f"\n{YELLOW}Ready for live sensor test on GPIO {pin}.{NC}")
        try:
            answer = input("Run live test? (y/n) [y]: ").strip().lower()
        except EOFError:
            answer = "n"
        if answer in ("", "y", "yes"):
            test_sensor_live(pin)
        else:
            info("Live test", "skipped")
    elif not p["is_arm"]:
        info("Live test", "skipped (not running on Raspberry Pi)")
    else:
        warn("Live test", "skipped (missing gpiozero or lgpio)")

    print()


if __name__ == "__main__":
    main()
