"""
PIR Sensor Integration for Calendar Application
Handles motion detection using a PIR sensor connected to GPIO pin
"""

import logging
import time
from collections.abc import Callable

from src.config import get_config

# Try to import RPi.GPIO, but handle cases where it's not available
# (development environments)
try:
    from RPi import GPIO

    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False

# Global list to store callbacks for motion detection
_motion_callbacks: list[Callable] = []

# Module-specific logger
logger = logging.getLogger(__name__)


def add_motion_callback(callback: Callable) -> None:
    """Add a callback function to be called when motion is detected"""
    if callback not in _motion_callbacks:
        _motion_callbacks.append(callback)


def remove_motion_callback(callback: Callable) -> None:
    """Remove a callback function"""
    if callback in _motion_callbacks:
        _motion_callbacks.remove(callback)


def trigger_motion_callbacks() -> None:
    """Trigger all registered motion callbacks"""
    for callback in _motion_callbacks:
        try:
            callback()
        except Exception:
            logger.exception("Error in motion callback")


class PIRSensor:
    """PIR Sensor class for motion detection"""

    def __init__(
        self,
        pin: int = 18,
        callback: Callable | None = None,
        debounce_time: float = 2.0,
    ) -> None:
        """
        Initialize PIR sensor

        Args:
            pin: GPIO pin number for PIR sensor (default: 18)
            callback: Function to call when motion is detected
            debounce_time: Minimum time between motion detections in seconds
        """
        config = get_config()

        self.pin = config.get("pir_sensor.gpio_pin", pin)
        self.callback = callback
        self.debounce_time = config.get("pir_sensor.debounce_time", debounce_time)
        self.last_detection_time: float = 0.0
        self.is_monitoring = False
        self.monitor_thread = None
        self.gpio_available = HAS_GPIO

        if not self.gpio_available:
            logger.warning(
                "RPi.GPIO not available - PIR sensor will use simulation mode",
            )

    def setup(self) -> bool:
        """
        Setup GPIO pin for PIR sensor

        Returns:
            bool: True if setup successful, False otherwise
        """
        if not self.gpio_available:
            logger.info("PIR sensor simulation mode - would use pin %s", self.pin)
            return True

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        except Exception:
            logger.exception("Failed to setup PIR sensor on pin %s", self.pin)
            return False
        else:
            logger.info("PIR sensor initialized on GPIO pin %s", self.pin)
            return True

    def set_callback(self, callback: Callable) -> None:
        """Set the callback function for motion detection"""
        self.callback = callback

    def _motion_detected(self, channel: int | None = None) -> None:
        """Internal method called when motion is detected"""
        # channel parameter required by GPIO callback interface but unused
        _ = channel  # Suppress vulture warning
        current_time = time.time()

        # Debounce detection
        if current_time - self.last_detection_time < self.debounce_time:
            return

        self.last_detection_time = current_time
        logger.info("Motion detected by PIR sensor")

        # Call the instance callback
        if self.callback:
            try:
                self.callback()
            except Exception:
                logger.exception("Error in PIR sensor callback")

        # Trigger global callbacks for WebSocket/API integration
        trigger_motion_callbacks()

    def start_monitoring(self) -> bool:
        """
        Start monitoring for motion

        Returns:
            bool: True if monitoring started successfully
        """
        if self.is_monitoring:
            logger.warning("PIR sensor monitoring already started")
            return True

        if not self.setup():
            return False

        self.is_monitoring = True

        if self.gpio_available:
            try:
                # Set up interrupt for motion detection
                GPIO.add_event_detect(
                    self.pin,
                    GPIO.RISING,
                    callback=self._motion_detected,
                    bouncetime=int(self.debounce_time * 1000),
                )
            except Exception:
                logger.exception("Failed to start PIR sensor monitoring")
                self.is_monitoring = False
                return False
            else:
                logger.info("PIR sensor monitoring started")
                return True
        else:
            # Development mode - PIR simulation disabled to prevent interference
            # with slideshow
            logger.info("PIR sensor simulation mode disabled on development machines")
            return True

    def _simulate_motion(self) -> None:
        """Simulate motion detection for development/testing"""
        while self.is_monitoring:
            time.sleep(30)  # Simulate motion every 30 seconds
            if self.is_monitoring:  # Check again in case monitoring was stopped
                self._motion_detected()

    def stop_monitoring(self) -> None:
        """Stop monitoring for motion"""
        if not self.is_monitoring:
            return

        self.is_monitoring = False

        if self.gpio_available:
            try:
                GPIO.remove_event_detect(self.pin)
                logger.info("PIR sensor monitoring stopped")
            except Exception:
                logger.exception("Error stopping PIR sensor monitoring")
        else:
            logger.info("PIR sensor development mode - no simulation to stop")

    def cleanup(self) -> None:
        """Clean up GPIO resources"""
        self.stop_monitoring()
        if self.gpio_available:
            try:
                GPIO.cleanup(self.pin)
                logger.info("PIR sensor GPIO cleaned up")
            except Exception:
                logger.exception("Error cleaning up PIR sensor GPIO")


# Global PIR sensor instance
_pir_sensor: PIRSensor | None = None


def initialize_pir_sensor(
    pin: int = 18,
    callback: Callable | None = None,
) -> PIRSensor:
    """
    Initialize the global PIR sensor instance

    Args:
        pin: GPIO pin number for PIR sensor
        callback: Function to call when motion is detected

    Returns:
        PIRSensor: The initialized sensor instance
    """
    global _pir_sensor  # noqa: PLW0603
    _pir_sensor = PIRSensor(pin=pin, callback=callback)
    return _pir_sensor


def get_pir_sensor() -> PIRSensor | None:
    """Get the global PIR sensor instance"""
    return _pir_sensor


def start_pir_monitoring() -> bool:
    """Start PIR sensor monitoring"""
    if _pir_sensor:
        return _pir_sensor.start_monitoring()
    return False


def stop_pir_monitoring() -> None:
    """Stop PIR sensor monitoring"""
    if _pir_sensor:
        _pir_sensor.stop_monitoring()


def cleanup_pir_sensor() -> None:
    """Clean up PIR sensor resources"""
    if _pir_sensor:
        _pir_sensor.cleanup()
