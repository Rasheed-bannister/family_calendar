"""Tests for src/pir_sensor/routes.py.

The sensor is opened once by the runtime, never over HTTP, so the surface
is status, a debug-only test trigger and diagnostics.
"""

from unittest.mock import patch

import pytest

from src import events
from src.events import broker
from src.main import create_app
from src.pir_sensor import sensor as sensor_module
from src.pir_sensor.routes import motion_detected_sse
from src.pir_sensor.sensor import PIRSensor

SAME_ORIGIN = "http://localhost"
FOREIGN_ORIGIN = "http://evil.example.com"


class StubConfig:
    def __init__(self, debug=False, environment="production"):
        self._debug = debug
        self._environment = environment

    def get(self, key, default=None):
        if key == "app.debug":
            return self._debug
        return default

    def is_production(self):
        return self._environment == "production"


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def isolate_sensor_globals():
    saved_callbacks = list(sensor_module._motion_callbacks)
    saved_sensor = sensor_module._pir_sensor
    yield
    sensor_module._motion_callbacks[:] = saved_callbacks
    sensor_module._pir_sensor = saved_sensor


@pytest.fixture
def no_sensor():
    sensor_module.set_pir_sensor(None)


@pytest.fixture
def sensor():
    """A simulation-mode sensor installed as the process singleton."""
    instance = PIRSensor(pin=18, simulation=True)
    instance.open()
    sensor_module.set_pir_sensor(instance)
    return instance


@pytest.fixture
def subscription():
    queue = broker.subscribe()
    yield queue
    broker.unsubscribe(queue)


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def _debug_config(debug=True, environment="development"):
    return patch(
        "src.config.get_config",
        return_value=StubConfig(debug=debug, environment=environment),
    )


class TestStatus:
    def test_not_initialized(self, client, no_sensor):
        data = client.get("/pir/status").get_json()
        assert data["initialized"] is False
        assert data["available"] is False
        assert "not initialized" in data["error"]

    def test_reports_sensor_status(self, client, sensor):
        data = client.get("/pir/status").get_json()
        assert data["initialized"] is True
        assert data["simulation"] is True
        assert data["available"] is False
        assert data["pin"] == 18
        assert data["error"] is None

    def test_reports_hardware_failure_loudly(self, client):
        broken = PIRSensor(pin=18)
        broken.error = "RuntimeError: EPERM"
        sensor_module.set_pir_sensor(broken)
        data = client.get("/pir/status").get_json()
        assert data["available"] is False
        assert data["error"] == "RuntimeError: EPERM"


class TestRemovedEndpoints:
    """Start/stop over HTTP is what used to wedge the sensor; it is gone."""

    @pytest.mark.parametrize("path", ["/pir/start", "/pir/stop"])
    def test_start_stop_are_gone(self, client, sensor, path):
        assert client.post(path).status_code == 404

    def test_legacy_event_stream_is_gone(self, client):
        assert client.get("/pir/events").status_code == 404


class TestCrossOriginGuard:
    def test_foreign_origin_is_rejected(self, client, sensor):
        with _debug_config():
            response = client.post(
                "/pir/trigger_test", headers={"Origin": FOREIGN_ORIGIN}
            )
        assert response.status_code == 403
        assert response.get_json()["success"] is False

    def test_rejected_request_publishes_nothing(self, client, sensor, subscription):
        with _debug_config():
            client.post("/pir/trigger_test", headers={"Origin": FOREIGN_ORIGIN})
        assert _drain(subscription) == []

    def test_foreign_referer_is_rejected_when_origin_is_absent(self, client, sensor):
        with _debug_config():
            response = client.post(
                "/pir/trigger_test",
                headers={"Referer": f"{FOREIGN_ORIGIN}/attack.html"},
            )
        assert response.status_code == 403

    def test_same_origin_referer_is_accepted(self, client, sensor):
        with _debug_config():
            response = client.post(
                "/pir/trigger_test", headers={"Referer": f"{SAME_ORIGIN}/index.html"}
            )
        assert response.status_code == 200

    def test_opaque_null_origin_is_rejected(self, client, sensor):
        with _debug_config():
            response = client.post("/pir/trigger_test", headers={"Origin": "null"})
        assert response.status_code == 403

    def test_same_host_on_another_port_is_rejected(self, client, sensor):
        with _debug_config():
            response = client.post(
                "/pir/trigger_test", headers={"Origin": "http://localhost:8080"}
            )
        assert response.status_code == 403

    def test_origin_wins_over_referer(self, client, sensor):
        with _debug_config():
            response = client.post(
                "/pir/trigger_test",
                headers={
                    "Origin": FOREIGN_ORIGIN,
                    "Referer": f"{SAME_ORIGIN}/index.html",
                },
            )
        assert response.status_code == 403


class TestTriggerTestGating:
    def test_disabled_in_production(self, client, sensor, subscription):
        with _debug_config(debug=False, environment="production"):
            response = client.post("/pir/trigger_test")
        assert response.status_code == 403
        assert _drain(subscription) == []

    def test_enabled_by_debug_flag(self, client, sensor, subscription):
        with _debug_config(debug=True, environment="production"):
            response = client.post("/pir/trigger_test")
        assert response.status_code == 200
        assert [e["type"] for e in _drain(subscription)] == [events.MOTION_DETECTED]

    def test_enabled_outside_production(self, client, sensor, subscription):
        with _debug_config(debug=False, environment="development"):
            response = client.post("/pir/trigger_test")
        assert response.status_code == 200
        assert sensor.motion_count == 1

    def test_without_a_sensor_the_event_still_fans_out(
        self, client, no_sensor, subscription
    ):
        with _debug_config():
            response = client.post("/pir/trigger_test")
        assert response.status_code == 200
        assert [e["type"] for e in _drain(subscription)] == [events.MOTION_DETECTED]

    def test_config_failure_fails_closed(self, client, sensor):
        with patch("src.config.get_config", side_effect=RuntimeError("no config")):
            response = client.post("/pir/trigger_test")
        assert response.status_code == 403


class TestMotionReachesTheBroker:
    def test_callback_publishes_motion_event(self, subscription):
        motion_detected_sse()
        published = _drain(subscription)
        assert len(published) == 1
        assert published[0]["type"] == events.MOTION_DETECTED

    def test_sensor_motion_reaches_subscribers(self, sensor, subscription):
        """The route module registered its callback at import time."""
        sensor.simulate_motion()
        assert [e["type"] for e in _drain(subscription)] == [events.MOTION_DETECTED]

    def test_shares_the_global_broker(self):
        from src.pir_sensor import routes as pir_routes

        assert pir_routes.broker is broker


class TestDiagnostics:
    def test_returns_check_results(self, client):
        with patch(
            "src.pir_sensor.diagnostics.run_all_checks",
            return_value={"issues": [], "platform": {"is_arm": False}},
        ):
            response = client.get("/pir/diagnostics")
        assert response.status_code == 200
        assert response.get_json()["issues"] == []

    def test_failure_returns_json_error(self, client):
        with patch(
            "src.pir_sensor.diagnostics.run_all_checks",
            side_effect=RuntimeError("boom"),
        ):
            response = client.get("/pir/diagnostics")
        assert response.status_code == 500
        assert response.get_json()["error"]

    def test_real_checks_report_the_installed_sensor(self, client, sensor):
        data = client.get("/pir/diagnostics").get_json()
        assert data["sensor"]["initialized"] is True
        assert data["sensor"]["simulation"] is True
        assert "issues" in data
