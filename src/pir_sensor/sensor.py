"""
PIR Sensor Integration for Calendar Application
Handles motion detection using a PIR sensor connected to GPIO pin.
Uses gpiozero for broad Raspberry Pi support (Pi 3, 4, and 5).
"""

import atexit
import logging
import signal
import threading
import time
from typing import Callable, Optional

# Try to import gpiozero, but handle cases where it's not available
try:
    from gpiozero import MotionSensor
    from gpiozero.exc import BadPinFactory, GPIOZeroError

    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False

# Valid BCM GPIO pin range on Raspberry Pi
_VALID_GPIO_PINS = set(range(0, 28))

# Global list to store callbacks for motion detection
_motion_callbacks: list[Callable] = []


def add_motion_callback(callback: Callable):
    """Add a callback function to be called when motion is detected"""
    if callback not in _motion_callbacks:
        _motion_callbacks.append(callback)


def trigger_motion_callbacks():
    """Trigger all registered motion callbacks"""
    for callback in _motion_callbacks:
        try:
            callback()
        except Exception as e:
            logging.error(f"Error in motion callback: {e}")


class PIRSensor:
    """PIR Sensor class for motion detection"""

    def __init__(
        self,
        pin: int = 18,
        callback: Optional[Callable] = None,
        debounce_time: float = 2.0,
    ):
        from src.config import get_config

        config = get_config()

        self.pin = config.get("pir_sensor.gpio_pin", pin)
        self.callback = callback
        self.debounce_time = config.get("pir_sensor.debounce_time", debounce_time)
        self.simulation_mode = config.get("pir_sensor.simulation_mode", False)
        self.last_detection_time = 0
        self.is_monitoring = False
        self._sensor: Optional[MotionSensor] = None if HAS_GPIO else None
        self.gpio_available = HAS_GPIO and not self.simulation_mode

        # Validate GPIO pin
        if self.pin not in _VALID_GPIO_PINS:
            logging.error(
                f"Invalid GPIO pin {self.pin} (must be 0-27). "
                f"Falling back to simulation mode."
            )
            self.gpio_available = False

        if not self.gpio_available:
            if self.simulation_mode:
                logging.info(
                    "PIR sensor running in simulation mode (simulation_mode=true)"
                )
            else:
                logging.warning(
                    "gpiozero not available — PIR sensor running in simulation mode"
                )

    def setup(self) -> bool:
        """Setup GPIO pin for PIR sensor using gpiozero MotionSensor."""
        if not self.gpio_available:
            return True

        try:
            self._sensor = MotionSensor(
                self.pin,
                queue_len=1,
                sample_rate=10,
                threshold=0.5,
            )
            logging.info(f"PIR sensor initialized on GPIO pin {self.pin}")
            return True
        except (GPIOZeroError, BadPinFactory) as e:
            logging.error(f"Failed to setup PIR sensor on pin {self.pin}: {e}")
            self.gpio_available = False
            return False
        except Exception as e:
            logging.error(f"Failed to setup PIR sensor on pin {self.pin}: {e}")
            self.gpio_available = False
            return False

    def _motion_detected(self):
        """Internal method called when motion is detected"""
        current_time = time.time()

        # Debounce detection
        if current_time - self.last_detection_time < self.debounce_time:
            return

        self.last_detection_time = current_time
        logging.info("Motion detected by PIR sensor")

        # Call the instance callback
        if self.callback:
            try:
                self.callback()
            except Exception as e:
                logging.error(f"Error in PIR sensor callback: {e}")

        # Trigger global callbacks (SSE broadcast, etc.)
        trigger_motion_callbacks()

    def start_monitoring(self) -> bool:
        """Start monitoring for motion."""
        if self.is_monitoring:
            return True

        if not self.setup():
            return False

        self.is_monitoring = True

        if self.gpio_available and self._sensor:
            try:
                self._sensor.when_motion = self._motion_detected
                logging.info("PIR sensor monitoring started (gpiozero)")
                return True
            except Exception as e:
                logging.error(f"Failed to start PIR sensor monitoring: {e}")
                self.is_monitoring = False
                return False
        else:
            # Simulation mode — no hardware to poll, status endpoints still work
            logging.info("PIR sensor monitoring started (simulation mode)")
            return True

    def stop_monitoring(self):
        """Stop monitoring for motion"""
        if not self.is_monitoring:
            return

        self.is_monitoring = False

        if self.gpio_available and self._sensor:
            try:
                self._sensor.when_motion = None
                logging.info("PIR sensor monitoring stopped")
            except Exception as e:
                logging.error(f"Error stopping PIR sensor monitoring: {e}")

    def cleanup(self):
        """Clean up GPIO resources"""
        self.stop_monitoring()
        if self._sensor:
            try:
                self._sensor.close()
                self._sensor = None
                logging.info("PIR sensor GPIO cleaned up")
            except Exception as e:
                logging.error(f"Error cleaning up PIR sensor GPIO: {e}")


# Global PIR sensor instance
_pir_sensor: Optional[PIRSensor] = None
_init_lock = threading.Lock()


def initialize_pir_sensor(
    pin: int = 18, callback: Optional[Callable] = None
) -> PIRSensor:
    """Initialize the global PIR sensor instance (thread-safe)."""
    global _pir_sensor
    with _init_lock:
        _pir_sensor = PIRSensor(pin=pin, callback=callback)

    # Register cleanup for graceful shutdown so GPIO is always released
    atexit.register(_cleanup_on_exit)
    signal.signal(signal.SIGTERM, _signal_handler)

    return _pir_sensor


def _cleanup_on_exit():
    """atexit handler to release GPIO."""
    if _pir_sensor:
        _pir_sensor.cleanup()


def _signal_handler(signum, frame):  # noqa: ARG001
    """Handle SIGTERM to ensure GPIO cleanup before exit."""
    _cleanup_on_exit()
    raise SystemExit(0)


def get_pir_sensor() -> Optional[PIRSensor]:
    """Get the global PIR sensor instance"""
    return _pir_sensor


def start_pir_monitoring() -> bool:
    """Start PIR sensor monitoring"""
    if _pir_sensor:
        return _pir_sensor.start_monitoring()
    return False


def stop_pir_monitoring():
    """Stop PIR sensor monitoring"""
    if _pir_sensor:
        _pir_sensor.stop_monitoring()
