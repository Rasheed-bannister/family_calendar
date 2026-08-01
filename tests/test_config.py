"""Tests for src/config.py - Configuration management."""

import json
import logging
import logging.handlers
import os
from unittest.mock import patch

import pytest

from src.config import Config


@pytest.fixture(autouse=True)
def restore_root_logger():
    """Preserve global root-logger state across tests.

    Config._setup_logging() removes every existing root handler and installs
    its own, which would otherwise leak into unrelated tests (including
    pytest's own logging capture).
    """
    root_logger = logging.getLogger()
    saved_handlers = root_logger.handlers[:]
    saved_level = root_logger.level
    saved_third_party = {
        name: logging.getLogger(name).level for name in ("werkzeug", "urllib3")
    }

    yield

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        if handler not in saved_handlers:
            handler.close()
    for handler in saved_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(saved_level)
    for name, level in saved_third_party.items():
        logging.getLogger(name).setLevel(level)


def _file_handlers(logger_obj):
    """Return handlers on ``logger_obj`` that write to a file on disk."""
    return [h for h in logger_obj.handlers if isinstance(h, logging.FileHandler)]


@pytest.fixture
def minimal_config_file(tmp_path):
    """Create a minimal valid config file."""
    config_data = {
        "app": {
            "debug": False,
            "host": "0.0.0.0",
            "port": 5000,
            "secret_key": "test-secret-key-1234567890abcdef",
            "use_reloader": False,
            "environment": "testing",
            "family_name": "TestFamily",
        },
        "weather": {
            "latitude": 40.0,
            "longitude": -74.0,
            "timezone": "America/New_York",
            "cache_duration": 600,
            "offline_fallback": True,
        },
        "pir_sensor": {"enabled": False, "gpio_pin": 18, "debounce_time": 2.0},
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
            "photos_dir": str(tmp_path / "photos"),
            "credentials_dir": str(tmp_path / "creds"),
        },
        "logging": {
            "level": "WARN",
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "file": str(tmp_path / "test.log"),
            "max_bytes": 10485760,
            "backup_count": 5,
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, indent=2))
    return str(config_path)


class TestDeepMerge:
    """Tests for Config._deep_merge."""

    def test_simple_merge(self, minimal_config_file):
        config = Config(minimal_config_file)
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = config._deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self, minimal_config_file):
        config = Config(minimal_config_file)
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        result = config._deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_override_dict_with_scalar(self, minimal_config_file):
        config = Config(minimal_config_file)
        base = {"a": {"x": 1}}
        override = {"a": "replaced"}
        result = config._deep_merge(base, override)
        assert result == {"a": "replaced"}

    def test_empty_override(self, minimal_config_file):
        config = Config(minimal_config_file)
        base = {"a": 1, "b": 2}
        result = config._deep_merge(base, {})
        assert result == {"a": 1, "b": 2}


class TestConfigGet:
    """Tests for Config.get with dot notation."""

    def test_get_top_level(self, minimal_config_file):
        config = Config(minimal_config_file)
        assert config.get("app.debug") is False

    def test_get_nested(self, minimal_config_file):
        config = Config(minimal_config_file)
        assert config.get("app.port") == 5000

    def test_get_missing_key_returns_default(self, minimal_config_file):
        config = Config(minimal_config_file)
        assert config.get("nonexistent.key", "fallback") == "fallback"

    def test_get_missing_key_returns_none(self, minimal_config_file):
        config = Config(minimal_config_file)
        assert config.get("nonexistent.key") is None

    def test_get_family_name(self, minimal_config_file):
        config = Config(minimal_config_file)
        assert config.get("app.family_name") == "TestFamily"


class TestConfigSet:
    """Tests for Config.set with dot notation."""

    def test_set_existing_key(self, minimal_config_file):
        config = Config(minimal_config_file)
        config.set("app.debug", True)
        assert config.get("app.debug") is True

    def test_set_new_key(self, minimal_config_file):
        config = Config(minimal_config_file)
        config.set("app.new_setting", "hello")
        assert config.get("app.new_setting") == "hello"

    def test_set_creates_nested_dicts(self, minimal_config_file):
        config = Config(minimal_config_file)
        config.set("new_section.subsection.key", 42)
        assert config.get("new_section.subsection.key") == 42


class TestConfigValidation:
    """Tests for Config._validate_numeric_ranges."""

    def test_invalid_latitude(self, tmp_path):
        import copy

        config_data = copy.deepcopy(Config.DEFAULTS)
        config_data["weather"]["latitude"] = 200
        config_data["logging"]["file"] = str(tmp_path / "test.log")
        config_data["paths"] = {
            "photos_dir": str(tmp_path / "photos"),
            "credentials_dir": str(tmp_path / "creds"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data, indent=2))

        # Clear env overrides that could mask the invalid value
        env_clear = {
            k: v for k, v in os.environ.items() if not k.startswith("CALENDAR_")
        }
        with patch.dict(os.environ, env_clear, clear=True):
            with pytest.raises(ValueError, match="latitude"):
                Config(str(config_path))

    def test_invalid_port(self, tmp_path):
        config_data = Config.DEFAULTS.copy()
        config_data["app"] = dict(Config.DEFAULTS["app"])
        config_data["app"]["port"] = 99999
        config_data["logging"] = dict(Config.DEFAULTS["logging"])
        config_data["logging"]["file"] = str(tmp_path / "test.log")
        config_data["paths"] = {
            "photos_dir": str(tmp_path / "photos"),
            "credentials_dir": str(tmp_path / "creds"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data, indent=2))

        with pytest.raises(ValueError, match="Port"):
            Config(str(config_path))


class TestConfigEnvironment:
    """Tests for Config environment mode checks."""

    def test_is_production(self, minimal_config_file):
        config = Config(minimal_config_file)
        config.set("app.environment", "production")
        assert config.is_production() is True
        assert config.is_development() is False

    def test_is_development(self, minimal_config_file):
        config = Config(minimal_config_file)
        config.set("app.environment", "development")
        assert config.is_development() is True
        assert config.is_production() is False


class TestConfigEnvOverrides:
    """Tests for environment variable overrides."""

    def test_env_override_port(self, minimal_config_file):
        with patch.dict(os.environ, {"CALENDAR_PORT": "8080"}):
            config = Config(minimal_config_file)
            assert config.get("app.port") == 8080

    def test_env_override_debug(self, minimal_config_file):
        with patch.dict(os.environ, {"CALENDAR_DEBUG": "true"}):
            config = Config(minimal_config_file)
            assert config.get("app.debug") is True

    def test_env_override_timezone(self, minimal_config_file):
        with patch.dict(os.environ, {"CALENDAR_TIMEZONE": "US/Pacific"}):
            config = Config(minimal_config_file)
            assert config.get("weather.timezone") == "US/Pacific"


class TestConfigSecretKey:
    """Tests for secret key generation."""

    def test_generates_secret_key_when_missing(self, tmp_path):
        config_data = Config.DEFAULTS.copy()
        config_data["app"] = dict(Config.DEFAULTS["app"])
        config_data["app"]["secret_key"] = None
        config_data["logging"] = dict(Config.DEFAULTS["logging"])
        config_data["logging"]["file"] = str(tmp_path / "test.log")
        config_data["paths"] = {
            "photos_dir": str(tmp_path / "photos"),
            "credentials_dir": str(tmp_path / "creds"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data, indent=2))

        config = Config(str(config_path))
        assert config.get("app.secret_key") is not None
        assert len(config.get("app.secret_key")) == 64  # hex string of 32 bytes


def _config_with_logging(base_config_file, logging_overrides):
    """Rewrite a config file with the given ``logging`` section overrides."""
    with open(base_config_file, "r") as f:
        config_data = json.load(f)
    for key, value in logging_overrides.items():
        if value is None:
            config_data["logging"].pop(key, None)
        else:
            config_data["logging"][key] = value
    with open(base_config_file, "w") as f:
        json.dump(config_data, f, indent=2)
    return base_config_file


class TestConfigLogging:
    """Tests for Config._setup_logging handler wiring."""

    def test_exactly_one_file_handler(self, minimal_config_file):
        """Regression: a plain FileHandler and a RotatingFileHandler were both
        attached to the same path, duplicating output and breaking rotation."""
        Config(minimal_config_file)

        root_logger = logging.getLogger()
        file_handlers = _file_handlers(root_logger)
        assert len(file_handlers) == 1
        assert isinstance(file_handlers[0], logging.handlers.RotatingFileHandler)

    def test_console_handler_present_alongside_file_handler(self, minimal_config_file):
        Config(minimal_config_file)

        root_logger = logging.getLogger()
        console_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1
        assert len(root_logger.handlers) == 2

    def test_single_log_call_writes_single_line(self, minimal_config_file, tmp_path):
        Config(minimal_config_file)

        marker = "UNIQUE-LOG-MARKER-8675309"
        logging.getLogger("test.duplication").warning(marker)
        for handler in logging.getLogger().handlers:
            handler.flush()

        log_path = tmp_path / "test.log"
        contents = log_path.read_text()
        assert contents.count(marker) == 1

    def test_single_file_handler_when_max_bytes_missing(self, minimal_config_file):
        """An absent max_bytes must still yield exactly one file handler.

        The key is deep-merged from DEFAULTS, so it is removed from the
        effective config before re-running the logging setup.
        """
        config = Config(minimal_config_file)
        del config.config["logging"]["max_bytes"]
        config._setup_logging()

        file_handlers = _file_handlers(logging.getLogger())
        assert len(file_handlers) == 1
        assert file_handlers[0].maxBytes == 0  # rotation disabled, not duplicated

    def test_single_file_handler_when_max_bytes_zero(self, minimal_config_file):
        _config_with_logging(minimal_config_file, {"max_bytes": 0})
        Config(minimal_config_file)

        assert len(_file_handlers(logging.getLogger())) == 1

    def test_single_log_call_single_line_without_max_bytes(
        self, minimal_config_file, tmp_path
    ):
        config = Config(minimal_config_file)
        del config.config["logging"]["max_bytes"]
        config._setup_logging()

        marker = "UNIQUE-LOG-MARKER-NOROTATE"
        logging.getLogger("test.duplication").warning(marker)
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert (tmp_path / "test.log").read_text().count(marker) == 1

    def test_invalid_level_does_not_raise(self, minimal_config_file):
        _config_with_logging(minimal_config_file, {"level": "VERBOSE"})

        config = Config(minimal_config_file)  # must not raise AttributeError

        assert logging.getLogger().level == logging.WARNING
        assert config._invalid_log_level == "VERBOSE"

    def test_missing_level_does_not_raise(self, minimal_config_file):
        """An absent level key falls back instead of raising KeyError."""
        config = Config(minimal_config_file)
        del config.config["logging"]["level"]

        config._setup_logging()

        assert logging.getLogger().level == logging.WARNING

    def test_warn_level_still_supported(self, minimal_config_file):
        """WARN is the shipped default and must remain valid."""
        _config_with_logging(minimal_config_file, {"level": "WARN"})

        config = Config(minimal_config_file)

        assert logging.getLogger().level == logging.WARNING
        assert config._invalid_log_level is None

    def test_valid_level_applied_to_third_party_loggers(self, minimal_config_file):
        _config_with_logging(minimal_config_file, {"level": "DEBUG"})
        Config(minimal_config_file)

        assert logging.getLogger().level == logging.DEBUG
        assert logging.getLogger("werkzeug").level == logging.DEBUG
        assert logging.getLogger("urllib3").level == logging.DEBUG

    def test_invalid_level_falls_back_for_third_party_loggers(
        self, minimal_config_file
    ):
        _config_with_logging(minimal_config_file, {"level": "VERBOSE"})
        Config(minimal_config_file)

        assert logging.getLogger("werkzeug").level == logging.WARNING
        assert logging.getLogger("urllib3").level == logging.WARNING

    def test_rotation_uses_configured_max_bytes(self, minimal_config_file):
        _config_with_logging(
            minimal_config_file, {"max_bytes": 2048, "backup_count": 3}
        )
        Config(minimal_config_file)

        handler = _file_handlers(logging.getLogger())[0]
        assert handler.maxBytes == 2048
        assert handler.backupCount == 3
