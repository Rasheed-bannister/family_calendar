"""PIR Sensor Diagnostics - checks that can run from the web UI or CLI."""

import glob
import grp
import logging
import os
import platform
import pwd
import subprocess
import sys

logger = logging.getLogger(__name__)


def run_all_checks() -> dict:
    """Run every diagnostic check and return a structured result dict."""
    config = _check_config()
    results: dict = {
        "platform": _check_platform(),
        "libraries": _check_libraries(),
        "gpio_devices": _check_gpio_devices(),
        "config": config,
        "sensor": _check_sensor_state(),
        "gpio_probe": _probe_gpio(config.get("pin", 18)),
        "power": _check_power(),
        "issues": [],
    }

    # Summarise issues
    issues = results["issues"]
    p = results["platform"]
    if not p.get("is_arm"):
        issues.append("Not running on Raspberry Pi hardware")
    libs = results["libraries"]
    if not libs.get("gpiozero"):
        issues.append("gpiozero is not installed")
    if not libs.get("lgpio"):
        issues.append("lgpio is not installed (requires swig + liblgpio-dev)")
    if not libs.get("swig_installed"):
        issues.append("System package 'swig' is missing")
    if not libs.get("liblgpio_installed"):
        issues.append("System package 'liblgpio-dev' is missing")
    cfg = results["config"]
    if cfg.get("simulation_mode"):
        issues.append("Simulation mode is enabled in config.json")
    if not cfg.get("enabled", True):
        issues.append("PIR sensor is disabled in config.json")
    gpio = results["gpio_devices"]
    if not gpio.get("gpio_group"):
        issues.append(f"User '{gpio.get('username', '?')}' is not in the gpio group")
    sensor = results["sensor"]
    if not sensor.get("initialized"):
        issues.append("PIR sensor has not been initialized")
    elif (
        cfg.get("enabled", True)
        and not cfg.get("simulation_mode")
        and not sensor.get("available")
    ):
        probe = results["gpio_probe"]
        detail = sensor.get("error") or probe.get("error")
        if detail:
            issues.append(f"PIR sensor could not open GPIO: {detail}")
        else:
            issues.append("GPIO is not available to the sensor")
    chips = gpio.get("chips") or []
    if chips and not any(c.get("accessible") for c in chips):
        issues.append(
            "No /dev/gpiochip* device is writable by this process "
            "(check the systemd DeviceAllow lines and the gpio group)"
        )
    pwr = results["power"]
    if pwr.get("under_voltage_now") or pwr.get("under_voltage_occurred"):
        issues.append("Under-voltage detected - use a 5V/5A power supply")

    return results


# --- Individual checks ---


def _check_platform() -> dict:
    machine = platform.machine()
    is_arm = machine in ("aarch64", "armv7l", "armv6l")

    model = "unknown"
    try:
        with open("/proc/device-tree/model") as f:
            model = f.read().strip().rstrip("\x00")
    except (FileNotFoundError, PermissionError):
        pass

    return {
        "machine": machine,
        "is_arm": is_arm,
        "model": model,
        "kernel": platform.release(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_executable": sys.executable,
    }


def _check_libraries() -> dict:
    result: dict = {
        "gpiozero": None,
        "lgpio": None,
        "pin_factory": None,
        "swig_installed": False,
        "liblgpio_installed": False,
    }

    try:
        import gpiozero

        result["gpiozero"] = getattr(gpiozero, "__version__", "unknown")
    except ImportError:
        pass

    try:
        import lgpio

        result["lgpio"] = getattr(lgpio, "__version__", "unknown")
    except ImportError:
        pass

    if result["gpiozero"]:
        try:
            from gpiozero import Device

            factory = Device.pin_factory
            if factory:
                result["pin_factory"] = type(factory).__name__
        except Exception:
            pass

    # System packages
    try:
        rc = subprocess.run(
            ["which", "swig"],  # noqa: S603, S607
            capture_output=True,
            timeout=5,
        ).returncode
        result["swig_installed"] = rc == 0
    except Exception:
        pass

    try:
        rc = subprocess.run(
            ["dpkg", "-s", "liblgpio-dev"],  # noqa: S603, S607
            capture_output=True,
            timeout=5,
        ).returncode
        result["liblgpio_installed"] = rc == 0
    except Exception:
        pass

    return result


def _check_gpio_devices() -> dict:
    result: dict = {
        "chips": [],
        "gpiomem": False,
        "gpiomem_accessible": False,
        "username": "unknown",
        "gpio_group": False,
        "user_groups": [],
    }

    # GPIO chip devices, with the kernel label where lgpio can read it. The
    # header chip is found by label, not number (see sensor.HEADER_CHIP_LABELS).
    from src.pir_sensor.sensor import detect_header_chip, list_gpio_chips

    labelled = {c["path"]: c for c in list_gpio_chips()}
    chips = sorted(glob.glob("/dev/gpiochip*"))
    for chip in chips:
        try:
            accessible = os.access(chip, os.R_OK | os.W_OK)
            stat = os.stat(chip)
            group = grp.getgrgid(stat.st_gid).gr_name
            mode = oct(stat.st_mode)[-3:]
            info = labelled.get(chip, {})
            result["chips"].append(
                {
                    "path": chip,
                    "accessible": accessible,
                    "group": group,
                    "mode": mode,
                    "label": info.get("label"),
                    "lines": info.get("lines"),
                }
            )
        except Exception as e:
            result["chips"].append({"path": chip, "accessible": False, "error": str(e)})
    result["header_chip"] = detect_header_chip(list(labelled.values()))

    # /dev/gpiomem
    if os.path.exists("/dev/gpiomem"):
        result["gpiomem"] = True
        result["gpiomem_accessible"] = os.access("/dev/gpiomem", os.R_OK | os.W_OK)

    # User and groups
    try:
        username = pwd.getpwuid(os.getuid()).pw_name
        result["username"] = username
        user_groups = [g.gr_name for g in grp.getgrall() if username in g.gr_mem]
        user_groups.append(grp.getgrgid(os.getgid()).gr_name)
        result["user_groups"] = sorted(set(user_groups))
        result["gpio_group"] = "gpio" in result["user_groups"]
    except Exception:
        pass

    return result


def _check_config() -> dict:
    try:
        from src.config import get_config

        config = get_config()
        return {
            "pin": config.get("pir_sensor.gpio_pin", 18),
            "enabled": config.get("pir_sensor.enabled", True),
            "simulation_mode": config.get("pir_sensor.simulation_mode", False),
            "debounce_time": config.get("pir_sensor.debounce_time", 2.0),
        }
    except Exception as e:
        return {"error": str(e)}


def _check_sensor_state() -> dict:
    from src.pir_sensor.sensor import get_pir_sensor

    sensor = get_pir_sensor()
    if not sensor:
        return {"initialized": False, "available": False, "error": "not initialized"}
    return {"initialized": True, **sensor.status()}


def _probe_gpio(pin: int) -> dict:
    """Read the configured pin.

    If the app's sensor holds the pin, read through it rather than fighting
    over the pin. Only when the app failed to open the pin is an independent
    probe attempted, to surface the real error message.
    """
    result: dict = {"success": False, "pin": pin, "error": None, "value": None}

    from src.pir_sensor.sensor import get_pir_sensor

    live = get_pir_sensor()
    if live and live.available and live._sensor is not None:
        try:
            result["success"] = True
            result["value"] = live._sensor.value
            return result
        except Exception as e:
            result["error"] = f"Could not read live sensor: {e}"
            return result
    if live and live.error:
        # The app already tried and recorded why it failed; a second probe
        # would only return the same error or a misleading "pin in use".
        result["error"] = live.error
        return result

    try:
        from gpiozero import MotionSensor
    except ImportError:
        result["error"] = "gpiozero not installed"
        return result

    sensor = None
    try:
        sensor = MotionSensor(pin, queue_len=1, sample_rate=10, threshold=0.5)
        result["success"] = True
        result["value"] = sensor.value
    except Exception as e:
        result["error"] = str(e)
    finally:
        if sensor:
            try:
                sensor.close()
            except Exception:
                pass

    return result


def _check_power() -> dict:
    result: dict = {
        "available": False,
        "throttled_raw": None,
        "under_voltage_now": False,
        "under_voltage_occurred": False,
        "throttled_now": False,
        "throttled_occurred": False,
        "flags": [],
    }

    try:
        proc = subprocess.run(
            ["vcgencmd", "get_throttled"],  # noqa: S603, S607
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return result

        result["available"] = True
        raw = proc.stdout.strip()
        result["throttled_raw"] = raw

        val_str = raw.split("=")[-1].strip() if "=" in raw else raw
        val = int(val_str, 16)

        flag_map = {
            0x1: ("under_voltage_now", "Under-voltage detected NOW"),
            0x2: ("arm_freq_capped_now", "ARM frequency capped NOW"),
            0x4: ("throttled_now", "Currently throttled"),
            0x8: ("soft_temp_limit_now", "Soft temperature limit active"),
            0x10000: ("under_voltage_occurred", "Under-voltage has occurred"),
            0x20000: ("arm_freq_capped_occurred", "ARM frequency was capped"),
            0x40000: ("throttled_occurred", "Throttling has occurred"),
            0x80000: ("soft_temp_limit_occurred", "Soft temperature limit occurred"),
        }

        for bit, (key, label) in flag_map.items():
            if val & bit:
                result[key] = True
                result["flags"].append(label)

    except FileNotFoundError:
        pass
    except Exception as e:
        result["error"] = str(e)

    return result
