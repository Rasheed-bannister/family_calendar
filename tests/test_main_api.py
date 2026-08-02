"""Tests for src/main.py API endpoints, in particular /api/config exposure."""

import pytest

from src.config import get_config
from src.main import PUBLIC_CONFIG_KEYS, _build_public_config, create_app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            pass
        yield client


def _collect_keys(obj, found=None):
    """Recursively collect every key name appearing in a nested structure."""
    if found is None:
        found = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            found.add(key)
            _collect_keys(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, found)
    return found


def _collect_values(obj, found=None):
    """Recursively collect every scalar value appearing in a nested structure."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for value in obj.values():
            _collect_values(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_values(item, found)
    else:
        found.append(obj)
    return found


class TestConfigApiSecrecy:
    """The /api/config endpoint must not leak sensitive configuration."""

    def test_no_secret_key_at_any_depth(self, client):
        """No key named secret_key may appear anywhere in the response."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.get_json()

        keys = _collect_keys(data)
        assert "secret_key" not in keys
        assert not any("secret" in key.lower() for key in keys)

    def test_secret_key_value_not_present(self, client):
        """The actual secret key value must not appear in the response."""
        secret_key = get_config().get("app.secret_key")
        assert secret_key, "expected the app to have a secret key configured"

        response = client.get("/api/config")
        assert secret_key not in response.get_data(as_text=True)
        assert secret_key not in _collect_values(response.get_json())

    def test_sensitive_sections_absent(self, client):
        """Sections holding secrets, paths or logging config are not exposed."""
        data = client.get("/api/config").get_json()
        for section in ("app", "paths", "logging", "weather", "pir_sensor"):
            assert section not in data

    def test_only_allowlisted_sections_returned(self, client):
        """The response contains exactly the allowlisted sections."""
        data = client.get("/api/config").get_json()
        assert set(data.keys()) == set(PUBLIC_CONFIG_KEYS.keys())

    def test_only_allowlisted_keys_within_sections(self, client):
        """No extra keys sneak into an exposed section."""
        data = client.get("/api/config").get_json()
        for section, allowed in PUBLIC_CONFIG_KEYS.items():
            assert set(data[section]).issubset(set(allowed))


class TestConfigApiFrontendContract:
    """The frontend still receives everything it dereferences."""

    def test_response_is_nested_by_section(self, client):
        """Sections must stay nested dicts; flattening breaks all JS reads."""
        data = client.get("/api/config").get_json()
        for section in PUBLIC_CONFIG_KEYS:
            assert isinstance(data[section], dict)

    @pytest.mark.parametrize(
        "key",
        [
            # static/js/app.js loadConfig()
            "day_timeout_minutes",
            "night_timeout_seconds",
            "day_brightness_reduction",
            "night_brightness_reduction",
            "night_start_hour",
            "night_end_hour",
            # Backend name; app.js reads slideshow_start_delay_seconds
            # (known mismatch, tracked separately).
            "slideshow_delay_seconds",
        ],
    )
    def test_inactivity_keys_present(self, client, key):
        data = client.get("/api/config").get_json()
        assert key in data["inactivity"]

    def test_google_sync_interval_present(self, client):
        """calendar.js and dailyView.js read config.google.sync_interval_minutes."""
        data = client.get("/api/config").get_json()
        assert "sync_interval_minutes" in data["google"]

    @pytest.mark.parametrize(
        "key",
        [
            "show_loading_indicators",  # loadingIndicator.js
            "show_pir_feedback",  # pirSensor.js
            "enhanced_virtual_keyboard",  # virtualKeyboard.js
            "touch_optimized",  # virtualKeyboard.js
            "animation_duration_ms",  # virtualKeyboard.js, pirSensor.js
        ],
    )
    def test_ui_keys_present(self, client, key):
        data = client.get("/api/config").get_json()
        assert key in data["ui"]


class TestBuildPublicConfig:
    """Unit tests for the allowlist builder itself."""

    class _FakeConfig:
        def __init__(self, data):
            self.config = data

        def get(self, key, default=None):
            value = self.config
            for part in key.split("."):
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return default
            return value

    def test_drops_non_allowlisted_sections_and_keys(self):
        fake = self._FakeConfig(
            {
                # Fake value; this test asserts it never reaches the response.
                "app": {
                    "secret_key": "super-secret",  # pragma: allowlist secret
                    "port": 5000,
                },
                "paths": {"photos_dir": "/srv/photos"},
                "logging": {"file": "calendar.log"},
                "ui": {"touch_optimized": True, "internal_flag": "nope"},
                "google": {"sync_interval_minutes": 7, "max_retry_attempts": 3},
                "inactivity": {"night_start_hour": 22},
            }
        )
        public = _build_public_config(fake)

        assert set(public) == set(PUBLIC_CONFIG_KEYS)
        assert public["ui"] == {"touch_optimized": True}
        assert public["google"] == {"sync_interval_minutes": 7}
        assert public["inactivity"] == {"night_start_hour": 22}
        assert "super-secret" not in _collect_values(public)

    def test_missing_section_yields_empty_dict(self):
        fake = self._FakeConfig({"app": {"secret_key": "x"}})
        public = _build_public_config(fake)
        assert public == {"inactivity": {}, "google": {}, "ui": {}}
