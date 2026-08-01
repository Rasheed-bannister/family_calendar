"""
Configuration management for Family Calendar application.
Loads settings from config.json with defaults and validation.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Timezone used for every "what month/day is this?" decision in the app when
# nothing has been configured. Kept identical to the historical
# ``weather.timezone`` default so existing installs behave the same.
DEFAULT_TIMEZONE = "America/New_York"


class Config:
    """Configuration manager for the Family Calendar application."""

    # Logging level names accepted in config.json (mirrors logging module names)
    VALID_LOG_LEVELS = frozenset(
        {"CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"}
    )

    # Used when the configured logging level is missing or unrecognised
    FALLBACK_LOG_LEVEL = logging.WARNING

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
            # Timezone the calendar is displayed in. ``None`` means "fall back
            # to weather.timezone", which is what every pre-existing config.json
            # (and the CALENDAR_TIMEZONE env var) sets.
            "timezone": None,
        },
        "weather": {
            "latitude": 40.759010,
            "longitude": -73.984474,
            "timezone": "America/New_York",
            "cache_duration": 600,  # seconds
            "offline_fallback": True,
        },
        "pir_sensor": {
            "enabled": True,
            "gpio_pin": 18,
            "debounce_time": 2.0,
            "simulation_mode": False,
        },
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
        """Initialize configuration from file or defaults.

        Note: print() is used for early messages before logging is configured.
        After _setup_logging(), all messages use the logger.
        """
        self._early_messages: list[str] = []
        self._invalid_log_level: Any = None
        self.config_file = config_file or self._find_config_file()
        self.config = self._load_config()
        self._validate_config()
        self._setup_logging()
        # Flush early messages through the now-configured logger
        for msg in self._early_messages:
            logger.info(msg)
        self._early_messages.clear()

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
                self._early_messages.append(f"Found config file at: {location}")
                return location

        # If no config file exists, copy from config.default.json or generate one
        default_location = Path.cwd() / "config.json"
        default_template = Path(__file__).parent.parent / "config.default.json"

        if default_template.exists():
            import shutil

            shutil.copy2(default_template, default_location)
            self._early_messages.append(
                f"No config file found. Copied from {default_template}"
            )
        else:
            self._early_messages.append(
                f"No config file found. Creating default at: {default_location}"
            )
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
            self._early_messages.append(f"Error creating default config file: {e}")
            return

        self._early_messages.append(f"Created default configuration file at: {path}")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file with defaults as fallback."""
        config = self.DEFAULTS.copy()

        if self.config_file and Path(self.config_file).exists():
            try:
                with open(self.config_file, "r") as f:
                    file_config = json.load(f)
                    # Deep merge with defaults
                    config = self._deep_merge(config, file_config)
                    self._early_messages.append(
                        f"Loaded configuration from: {self.config_file}"
                    )
            except (ValueError, IOError) as e:
                self._early_messages.append(f"Error loading config file: {e}")
                self._early_messages.append("Using default configuration")

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
                    self._early_messages.append(f"Override from environment: {env_var}")
                except (ValueError, KeyError) as e:
                    self._early_messages.append(
                        f"Error applying environment override {env_var}: {e}"
                    )

    def _ensure_secret_key(self) -> None:
        """Ensure secret key exists or generate one."""
        if not self.config["app"].get("secret_key"):
            import secrets

            self.config["app"]["secret_key"] = secrets.token_hex(32)
            self._early_messages.append(
                "No secret key configured. Generated a random one."
            )

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
                self._early_messages.append(f"Configuration error: {error}")
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")

        self._early_messages.append("Configuration validation successful")

    def _resolve_log_level(self, raw_level: Any) -> int:
        """Translate a configured logging level into a numeric level.

        An unknown/invalid level must never crash application startup, so we
        fall back to the default level and record a warning instead.
        """
        if isinstance(raw_level, int) and not isinstance(raw_level, bool):
            return raw_level

        name = str(raw_level).strip().upper() if raw_level is not None else ""
        if name in self.VALID_LOG_LEVELS:
            return int(getattr(logging, name))

        self._invalid_log_level = raw_level
        return self.FALLBACK_LOG_LEVEL

    def _setup_logging(self):
        """Configure logging based on settings.

        Exactly one file handler is attached. A plain FileHandler must never be
        combined with a RotatingFileHandler on the same path: they would both
        emit every record (duplicate lines) and, after a rotation, the plain
        handler would keep writing to the renamed inode so the file grows
        without bound while appearing to rotate correctly.
        """
        from logging.handlers import RotatingFileHandler

        log_config = self.config["logging"]

        # Create logs directory if needed
        log_file = Path(log_config["file"])
        log_file.parent.mkdir(parents=True, exist_ok=True)

        self._invalid_log_level = None
        level = self._resolve_log_level(log_config.get("level"))

        # Clear any existing handlers and reconfigure completely
        root_logger = logging.getLogger()

        # Remove all existing handlers. File handlers are closed as they go so
        # repeated setup (e.g. reload_config) does not leak file descriptors
        # onto files that may since have been rotated away.
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            if isinstance(handler, logging.FileHandler):
                try:
                    handler.close()
                except OSError:  # pragma: no cover - defensive
                    pass

        # Set the logging level
        root_logger.setLevel(level)

        # Create formatter
        formatter = logging.Formatter(log_config["format"])

        # Single file handler. maxBytes=0 disables rotation, so a missing or
        # falsy max_bytes still yields exactly one file handler rather than
        # zero (no file logging) or two (duplicate lines + broken rotation).
        max_bytes = log_config.get("max_bytes") or 0
        try:
            max_bytes = int(max_bytes)
        except (TypeError, ValueError):
            max_bytes = 0
        if max_bytes < 0:
            max_bytes = 0

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=log_config.get("backup_count", 5) if max_bytes else 0,
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Add console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # Configure Flask/werkzeug loggers to respect the same level
        logging.getLogger("werkzeug").setLevel(level)

        # Configure other common third-party loggers
        logging.getLogger("urllib3").setLevel(level)

        # Now that handlers exist, surface any problem with the configured level
        if self._invalid_log_level is not None:
            logger.warning(
                "Invalid logging level %r in configuration; falling back to %s",
                self._invalid_log_level,
                logging.getLevelName(self.FALLBACK_LOG_LEVEL),
            )

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


def get_timezone_name() -> str:
    """Return the configured IANA timezone name for the calendar display.

    Resolution order:
      1. ``app.timezone`` - the dedicated key, for installs whose display
         timezone differs from the location they want weather for.
      2. ``weather.timezone`` - what every existing config.json (and the
         long-documented ``CALENDAR_TIMEZONE`` env var) already sets, so
         upgrading installs need no config change.
      3. :data:`DEFAULT_TIMEZONE`.
    """
    config = get_config()
    name = config.get("app.timezone") or config.get("weather.timezone")
    if not isinstance(name, str) or not name.strip():
        return DEFAULT_TIMEZONE
    return name.strip()


def get_local_timezone() -> ZoneInfo:
    """Return the configured display timezone as a :class:`ZoneInfo`.

    A bad/unknown timezone name must never take the calendar down, so an
    unresolvable name degrades to :data:`DEFAULT_TIMEZONE` and finally to UTC
    (which is all that is available if the tz database itself is missing).
    """
    name = get_timezone_name()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        logger.warning(
            "Unknown timezone %r in configuration; falling back to %s",
            name,
            DEFAULT_TIMEZONE,
        )

    try:
        return ZoneInfo(DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, OSError):  # pragma: no cover
        logger.error("Timezone database unavailable; falling back to UTC")
        return ZoneInfo("UTC")


def get_month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return the half-open ``[start, end)`` instants of a local calendar month.

    ``start`` is midnight on the 1st and ``end`` is midnight on the 1st of the
    following month, both in the configured display timezone. Callers that need
    UTC can simply ``.astimezone(timezone.utc)``.

    Computing this in local time is what keeps a 10pm event on the last day of
    the month inside that month's window; a hardcoded UTC window would cut the
    month short by the UTC offset.
    """
    tz = get_local_timezone()
    start = datetime(year, month, 1, tzinfo=tz)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=tz)
    else:
        end = datetime(year, month + 1, 1, tzinfo=tz)
    return start, end
