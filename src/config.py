"""
Configuration management for Family Calendar application.
Loads settings from config.json with defaults and validation.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """Configuration manager for the Family Calendar application."""

    # Default configuration values
    DEFAULTS: dict[str, dict[str, Any]] = {
        "app": {
            "debug": False,
            "host": "0.0.0.0",  # nosec B104 # Intentional for family calendar local network access
            "port": 5000,
            "secret_key": None,  # Should be set in config file
            "use_reloader": False,
            "environment": "production",  # production, development, testing
            "family_name": "Family",  # Default family name
        },
        "weather": {
            "latitude": 40.759010,
            "longitude": -73.984474,
            "timezone": "America/New_York",
            "cache_duration": 600,  # seconds
            "offline_fallback": True,
        },
        "pir_sensor": {"enabled": True, "gpio_pin": 18, "debounce_time": 2.0},
        "inactivity": {
            "day_timeout_minutes": 60,
            "night_timeout_seconds": 5,
            "day_brightness_reduction": 0.6,
            "night_brightness_reduction": 0.2,
            "night_start_hour": 21,
            "night_end_hour": 6,
            "slideshow_delay_seconds": 5,
        },
        "google": {"sync_interval_minutes": 3, "max_retry_attempts": 3},
        "ui": {
            "show_loading_indicators": False,
            "show_pir_feedback": False,
            "enhanced_virtual_keyboard": True,
            "touch_optimized": True,
            "animation_duration_ms": 300,
        },
        "paths": {
            "photos_dir": "src/static/photos",
            "credentials_dir": "src/google_integration",
        },
        "logging": {
            "level": "WARN",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": "calendar.log",
            "max_bytes": 10485760,  # 10MB
            "backup_count": 5,
        },
    }

    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration from file or defaults."""
        self.config_file = config_file or self._find_config_file()
        self.config = self._load_config()
        self._validate_config()
        self._setup_logging()

    def _find_config_file(self) -> Path:
        """Find the configuration file in standard locations."""
        # Check multiple locations in order of preference
        locations = [
            Path.cwd() / "config.json",
            Path.home() / ".calendar" / "config.json",
            Path(__file__).parent.parent / "config.json",
            Path("/etc/calendar/config.json"),
        ]

        for location in locations:
            if location.exists():
                # Use print here since logging isn't configured yet
                print(f"Found config file at: {location}")
                return location

        # If no config file exists, create a default one
        default_location = Path.cwd() / "config.json"
        print(f"No config file found. Creating default at: {default_location}")
        self._create_default_config(default_location)
        return default_location

    def _create_default_config(self, path: Path):
        """Create a default configuration file."""
        path.parent.mkdir(parents=True, exist_ok=True)

        # Generate a secret key for the default config
        import secrets

        default_config = self.DEFAULTS.copy()
        default_config["app"]["secret_key"] = secrets.token_hex(32)  # type: ignore[index]

        try:
            with open(path, "w") as f:
                json.dump(default_config, f, indent=2)
        except (IOError, ValueError) as e:
            print(f"Error creating default config file: {e}")
            return

        print(f"Created default configuration file at: {path}")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file with defaults as fallback."""
        config = self.DEFAULTS.copy()

        if self.config_file and Path(self.config_file).exists():
            try:
                with open(self.config_file, "r") as f:
                    file_config = json.load(f)
                    # Deep merge with defaults
                    config = self._deep_merge(config, file_config)
                    print(f"Loaded configuration from: {self.config_file}")
            except (ValueError, IOError) as e:
                print(f"Error loading config file: {e}")
                print("Using default configuration")

        # Override with environment variables if present (for backwards compatibility)
        self._apply_env_overrides(config)

        return config

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _apply_env_overrides(self, config: Dict):
        """Apply environment variable overrides for backwards compatibility."""
        env_mappings = {
            "CALENDAR_WEATHER_LATITUDE": ("weather", "latitude", float),
            "CALENDAR_WEATHER_LONGITUDE": ("weather", "longitude", float),
            "CALENDAR_TIMEZONE": ("weather", "timezone", str),
            "CALENDAR_DEBUG": ("app", "debug", lambda x: x.lower() == "true"),
            "CALENDAR_PORT": ("app", "port", int),
            "CALENDAR_ENV": ("app", "environment", str),
        }

        for env_var, (section, key, converter) in env_mappings.items():
            if env_var in os.environ:
                try:
                    config[section][key] = converter(os.environ[env_var])  # type: ignore[operator]
                    print(f"Override from environment: {env_var}")
                except (ValueError, KeyError) as e:
                    print(f"Error applying environment override {env_var}: {e}")

    def _ensure_secret_key(self) -> None:
        """Ensure secret key exists or generate one."""
        if not self.config["app"].get("secret_key"):
            import secrets

            self.config["app"]["secret_key"] = secrets.token_hex(32)
            print("No secret key configured. Generated a random one.")

    def _validate_numeric_ranges(self) -> list[str]:
        """Validate numeric configuration ranges.

        Returns:
            list: List of validation errors
        """
        errors = []

        # Validate latitude range
        latitude = self.config["weather"]["latitude"]
        if not -90 <= latitude <= 90:
            errors.append("Weather latitude must be between -90 and 90")

        # Validate longitude range
        longitude = self.config["weather"]["longitude"]
        if not -180 <= longitude <= 180:
            errors.append("Weather longitude must be between -180 and 180")

        # Validate port range
        port = self.config["app"]["port"]
        if not 1 <= port <= 65535:
            errors.append("Port must be between 1 and 65535")

        return errors

    def _validate_paths(self) -> list[str]:
        """Validate path configurations.

        Returns:
            list: List of validation errors
        """
        errors = []

        for path_key, path_value in self.config["paths"].items():
            if path_value and not Path(path_value).exists():
                try:
                    Path(path_value).mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    errors.append(f"Cannot create {path_key}: {e}")

        return errors

    def _validate_config(self) -> None:
        """Validate configuration values."""
        # Ensure required fields
        self._ensure_secret_key()

        # Collect all validation errors
        errors = []
        errors.extend(self._validate_numeric_ranges())
        errors.extend(self._validate_paths())

        # Report errors if any
        if errors:
            for error in errors:
                print(f"Configuration error: {error}")
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")

        print("Configuration validation successful")

    def _setup_logging(self):
        """Configure logging based on settings."""
        log_config = self.config["logging"]

        # Create logs directory if needed
        log_file = Path(log_config["file"])
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Clear any existing handlers and reconfigure completely
        root_logger = logging.getLogger()

        # Remove all existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Set the logging level
        root_logger.setLevel(getattr(logging, log_config["level"]))

        # Create formatter
        formatter = logging.Formatter(log_config["format"])

        # Add file handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # Add rotating file handler if specified
        if log_config.get("max_bytes"):
            from logging.handlers import RotatingFileHandler

            rotating_handler = RotatingFileHandler(
                log_file,
                maxBytes=log_config["max_bytes"],
                backupCount=log_config.get("backup_count", 5),
            )
            rotating_handler.setFormatter(formatter)
            root_logger.addHandler(rotating_handler)

        # Configure Flask/werkzeug loggers to respect the same level
        werkzeug_logger = logging.getLogger("werkzeug")
        werkzeug_logger.setLevel(getattr(logging, log_config["level"]))

        # Configure other common third-party loggers
        urllib3_logger = logging.getLogger("urllib3")
        urllib3_logger.setLevel(getattr(logging, log_config["level"]))

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation."""
        keys = key.split(".")
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any):
        """Set a configuration value using dot notation."""
        keys = key.split(".")
        target = self.config

        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]

        target[keys[-1]] = value

    def save(self):
        """Save current configuration to file."""
        if self.config_file:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=2)
            logging.info(f"Configuration saved to: {self.config_file}")

    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.config["app"]["environment"] == "production"

    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.config["app"]["environment"] == "development"

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access."""
        return self.config[key]

    def __contains__(self, key: str) -> bool:
        """Check if a key exists in config."""
        return key in self.config


# Global configuration instance
_config = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config():
    """Reload configuration from file."""
    global _config
    _config = Config()
    return _config
