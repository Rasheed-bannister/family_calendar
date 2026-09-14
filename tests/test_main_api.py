"""Tests for src/main.py: /api/config exposure and serving the built app."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src import main as main_module
from src.config import get_config
from src.main import PUBLIC_CONFIG_KEYS, _build_public_config, create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _collect_keys(obj, found=None):
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


# Keys the builder adds on top of the flat allowlist.
EXTRA_KEYS = {"app": {"timezone"}, "display": {"day", "night"}}


class TestConfigApiSecrecy:
    def test_no_secret_key_at_any_depth(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        keys = _collect_keys(response.get_json())
        assert not any("secret" in key.lower() for key in keys)

    def test_secret_key_value_not_present(self, client):
        secret_key = get_config().get("app.secret_key")
        assert secret_key
        response = client.get("/api/config")
        assert secret_key not in response.get_data(as_text=True)
        assert secret_key not in _collect_values(response.get_json())

    def test_sensitive_sections_absent(self, client):
        data = client.get("/api/config").get_json()
        for section in ("paths", "logging", "pir_sensor", "scheduler"):
            assert section not in data

    def test_app_section_only_carries_public_keys(self, client):
        data = client.get("/api/config").get_json()
        assert set(data["app"]) <= set(PUBLIC_CONFIG_KEYS["app"]) | EXTRA_KEYS["app"]
        assert "host" not in data["app"]
        assert "port" not in data["app"]

    def test_only_allowlisted_sections_returned(self, client):
        data = client.get("/api/config").get_json()
        assert set(data.keys()) == set(PUBLIC_CONFIG_KEYS.keys())

    def test_only_allowlisted_keys_within_sections(self, client):
        data = client.get("/api/config").get_json()
        for section, allowed in PUBLIC_CONFIG_KEYS.items():
            assert set(data[section]) <= set(allowed) | EXTRA_KEYS.get(section, set())


class TestConfigApiFrontendContract:
    """Everything frontend/src/lib/stores/config.svelte.ts dereferences."""

    def test_response_is_nested_by_section(self, client):
        data = client.get("/api/config").get_json()
        for section in PUBLIC_CONFIG_KEYS:
            assert isinstance(data[section], dict)

    def test_app_keys(self, client):
        data = client.get("/api/config").get_json()["app"]
        assert {"family_name", "timezone", "debug", "environment"} <= set(data)
        assert isinstance(data["timezone"], str) and data["timezone"]

    @pytest.mark.parametrize("period", ["day", "night"])
    @pytest.mark.parametrize(
        "key", ["dim_after_seconds", "hide_ui_after_seconds", "brightness"]
    )
    def test_display_thresholds(self, client, period, key):
        data = client.get("/api/config").get_json()["display"]
        assert key in data[period]
        assert {"night_start_hour", "night_end_hour"} <= set(data)

    def test_slideshow_keys(self, client):
        data = client.get("/api/config").get_json()["slideshow"]
        assert {"interval_seconds", "transition_seconds", "ken_burns"} <= set(data)

    def test_google_and_weather_keys(self, client):
        data = client.get("/api/config").get_json()
        assert "sync_interval_minutes" in data["google"]
        assert "cache_duration" in data["weather"]

    @pytest.mark.parametrize(
        "key", ["show_pir_feedback", "touch_optimized", "animation_duration_ms"]
    )
    def test_ui_keys_present(self, client, key):
        assert key in client.get("/api/config").get_json()["ui"]


class TestBuildPublicConfig:
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

    @pytest.fixture(autouse=True)
    def timezone_name(self):
        with patch("src.config.get_timezone_name", return_value="UTC"):
            yield

    def test_drops_non_allowlisted_sections_and_keys(self):
        fake = self._FakeConfig(
            {
                "app": {
                    "secret_key": "super-secret",  # pragma: allowlist secret
                    "port": 5000,
                    "family_name": "Smiths",
                },
                "paths": {"photos_dir": "/srv/photos"},
                "logging": {"file": "calendar.log"},
                "ui": {"touch_optimized": True, "internal_flag": "nope"},
                "google": {"sync_interval_minutes": 7, "max_retry_attempts": 3},
                "display": {
                    "night_start_hour": 22,
                    "backlight": {"backend": "sysfs"},
                    "day": {"dim_after_seconds": 1},
                },
            }
        )
        public = _build_public_config(fake)

        assert set(public) == set(PUBLIC_CONFIG_KEYS)
        assert public["ui"] == {"touch_optimized": True}
        assert public["google"] == {"sync_interval_minutes": 7}
        assert public["app"] == {"family_name": "Smiths", "timezone": "UTC"}
        assert public["display"] == {
            "night_start_hour": 22,
            "day": {"dim_after_seconds": 1},
            "night": {},
        }
        assert "backlight" not in public["display"]
        assert "super-secret" not in _collect_values(public)

    def test_missing_section_yields_empty_dict(self):
        public = _build_public_config(self._FakeConfig({"app": {"secret_key": "x"}}))
        assert public["slideshow"] == {}
        assert public["weather"] == {}
        assert public["display"] == {"day": {}, "night": {}}


class TestServingTheApp:
    def test_built_index_is_served_uncached(self, client, tmp_path):
        (tmp_path / "index.html").write_text("<!doctype html><title>built</title>")
        with patch.object(main_module, "FRONTEND_DIST_REL", tmp_path):
            client_app = create_app()
            client_app.config["TESTING"] = True
            response = client_app.test_client().get("/")
        assert response.status_code == 200
        assert response.mimetype == "text/html"
        assert b"built" in response.data
        assert response.headers["Cache-Control"] == "no-store"

    def test_missing_build_explains_itself(self, tmp_path):
        with patch.object(main_module, "FRONTEND_DIST_REL", tmp_path / "missing"):
            app = create_app()
            app.config["TESTING"] = True
            response = app.test_client().get("/")
        assert response.status_code == 200
        assert response.mimetype == "text/html"
        assert b"Frontend not built" in response.data
        assert b"npm run build" in response.data

    def test_dist_path_is_relative_to_the_static_folder(self):
        assert main_module.FRONTEND_DIST_REL == Path("app")

    def test_no_jinja_pages_are_rendered_for_the_display(self, client):
        """The display is the built SPA; the old server-rendered page is gone."""
        response = client.get("/")
        assert b'class="main-container"' not in response.data


class TestSseEndpoint:
    def test_events_stream_headers(self):
        client = create_app().test_client()
        response = client.get("/events", buffered=False)
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache"
        response.close()
