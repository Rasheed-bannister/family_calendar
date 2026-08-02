"""Tests for src/pir_sensor/routes.py.

Covers the status contract the frontend polls, the access control on the
state-changing endpoints, and the fact that motion reaches the shared event
broker rather than a list of the blueprint's own.
"""

from unittest.mock import Mock, patch

import pytest

from src import events
from src.events import broker
from src.main import create_app
from src.pir_sensor import routes as routes_module
from src.pir_sensor import sensor as sensor_module
from src.pir_sensor.sensor import PIRSensor

# Host the Flask test client presents itself as.
SAME_ORIGIN = "http://localhost"
FOREIGN_ORIGIN = "http://evil.example.com"


class StubConfig:
    """Minimal stand-in for src.config.Config."""

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
    """Create a Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        with app.app_context():
            pass
        yield client


@pytest.fixture(autouse=True)
def isolate_sensor_globals():
    """Restore the module-level sensor and callback list after every test."""
    saved_callbacks = list(sensor_module._motion_callbacks)
    saved_sensor = sensor_module._pir_sensor
    yield
    sensor_module._motion_callbacks[:] = saved_callbacks
    sensor_module._pir_sensor = saved_sensor


@pytest.fixture
def no_sensor():
    """No PIR sensor has been initialised."""
    sensor_module._pir_sensor = None


@pytest.fixture
def sensor():
    """Install a simulation-mode sensor as the module-level instance."""
    with patch("src.config.get_config", return_value=StubConfig()):
        instance = PIRSensor(pin=18)
    sensor_module._pir_sensor = instance
    return instance


@pytest.fixture
def subscription():
    """Subscribe to the shared broker and clean the subscription up."""
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
    """Shape of /pir/status, which pirSensor.js polls every 5 seconds."""

    def test_uninitialised_sensor_reports_not_initialized(self, client, no_sensor):
        response = client.get("/pir/status")
        assert response.status_code == 200
        assert response.get_json() == {
            "status": "not_initialized",
            "monitoring": False,
            "gpio_available": False,
        }

    def test_initialised_sensor_reports_its_state(self, client, sensor):
        response = client.get("/pir/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "initialized"
        assert data["monitoring"] is False
        assert data["gpio_available"] is False
        assert data["pin"] == 18

    def test_status_tracks_monitoring(self, client, sensor):
        sensor.start_monitoring()
        assert client.get("/pir/status").get_json()["monitoring"] is True
        sensor.stop_monitoring()
        assert client.get("/pir/status").get_json()["monitoring"] is False

    def test_status_needs_no_origin(self, client, sensor):
        """A read-only status poll is not guarded."""
        response = client.get("/pir/status", headers={"Origin": FOREIGN_ORIGIN})
        assert response.status_code == 200


class TestStartStop:
    """The endpoints pirSensor.js calls on init and on cleanup."""

    def test_start_begins_monitoring(self, client, sensor):
        response = client.post("/pir/start", headers={"Origin": SAME_ORIGIN})
        assert response.status_code == 200
        assert response.get_json()["success"] is True
        assert sensor.is_monitoring is True

    def test_start_without_an_origin_header_is_allowed(self, client, sensor):
        response = client.post("/pir/start")
        assert response.status_code == 200
        assert sensor.is_monitoring is True

    def test_start_is_idempotent_over_http(self, client, sensor):
        assert client.post("/pir/start").status_code == 200
        assert client.post("/pir/start").status_code == 200
        assert sensor.is_monitoring is True

    def test_start_without_a_sensor_reports_failure(self, client, no_sensor):
        response = client.post("/pir/start")
        assert response.status_code == 500
        assert response.get_json()["success"] is False

    def test_start_reports_failure_instead_of_raising(self, client, sensor):
        with patch.object(
            routes_module, "start_pir_monitoring", side_effect=RuntimeError("boom")
        ):
            response = client.post("/pir/start")
        assert response.status_code == 500
        assert response.get_json()["success"] is False

    def test_stop_ends_monitoring(self, client, sensor):
        sensor.start_monitoring()
        response = client.post("/pir/stop", headers={"Origin": SAME_ORIGIN})
        assert response.status_code == 200
        assert response.get_json()["success"] is True
        assert sensor.is_monitoring is False

    def test_stop_without_a_sensor_still_succeeds(self, client, no_sensor):
        assert client.post("/pir/stop").status_code == 200

    def test_stop_reports_failure_instead_of_raising(self, client, sensor):
        with patch.object(
            routes_module, "stop_pir_monitoring", side_effect=RuntimeError("boom")
        ):
            response = client.post("/pir/stop")
        assert response.status_code == 500

    def test_get_is_not_allowed_on_control_endpoints(self, client, sensor):
        assert client.get("/pir/start").status_code == 405
        assert client.get("/pir/stop").status_code == 405


class TestCrossOriginGuard:
    """A page on another site must not be able to drive the display."""

    @pytest.mark.parametrize("path", ["/pir/start", "/pir/stop", "/pir/trigger_test"])
    def test_foreign_origin_is_rejected(self, client, sensor, path):
        response = client.post(path, headers={"Origin": FOREIGN_ORIGIN})
        assert response.status_code == 403
        assert response.get_json()["success"] is False

    def test_rejected_request_has_no_effect(self, client, sensor):
        sensor.start_monitoring()
        client.post("/pir/stop", headers={"Origin": FOREIGN_ORIGIN})
        assert sensor.is_monitoring is True

    def test_rejected_request_publishes_nothing(self, client, sensor, subscription):
        with _debug_config():
            client.post("/pir/trigger_test", headers={"Origin": FOREIGN_ORIGIN})
        assert _drain(subscription) == []

    def test_foreign_referer_is_rejected_when_origin_is_absent(self, client, sensor):
        response = client.post(
            "/pir/start", headers={"Referer": f"{FOREIGN_ORIGIN}/attack.html"}
        )
        assert response.status_code == 403

    def test_same_origin_referer_is_accepted(self, client, sensor):
        response = client.post(
            "/pir/start", headers={"Referer": f"{SAME_ORIGIN}/index.html"}
        )
        assert response.status_code == 200

    def test_opaque_null_origin_is_rejected(self, client, sensor):
        """Sandboxed iframes and file:// pages send Origin: null."""
        response = client.post("/pir/start", headers={"Origin": "null"})
        assert response.status_code == 403

    def test_same_host_on_another_port_is_rejected(self, client, sensor):
        response = client.post(
            "/pir/start", headers={"Origin": "http://localhost:8080"}
        )
        assert response.status_code == 403

    def test_origin_wins_over_referer(self, client, sensor):
        response = client.post(
            "/pir/start",
            headers={
                "Origin": FOREIGN_ORIGIN,
                "Referer": f"{SAME_ORIGIN}/index.html",
            },
        )
        assert response.status_code == 403


class TestTriggerTestGating:
    """Fake motion is a debug affordance, not a production endpoint."""

    def test_enabled_helper_follows_the_config(self):
        with patch(
            "src.config.get_config",
            return_value=StubConfig(debug=False, environment="production"),
        ):
            assert routes_module._test_motion_enabled() is False
        with patch(
            "src.config.get_config",
            return_value=StubConfig(debug=True, environment="production"),
        ):
            assert routes_module._test_motion_enabled() is True
        with patch(
            "src.config.get_config",
            return_value=StubConfig(debug=False, environment="development"),
        ):
            assert routes_module._test_motion_enabled() is True

    def test_forbidden_on_a_production_install(self, client, sensor, subscription):
        with _debug_config(debug=False, environment="production"):
            response = client.post("/pir/trigger_test", headers={"Origin": SAME_ORIGIN})

        assert response.status_code == 403
        assert response.get_json()["success"] is False
        assert _drain(subscription) == []

    def test_allowed_when_debug_is_enabled(self, client, sensor, subscription):
        with _debug_config(debug=True, environment="production"):
            response = client.post("/pir/trigger_test", headers={"Origin": SAME_ORIGIN})

        assert response.status_code == 200
        assert response.get_json()["success"] is True
        [event] = _drain(subscription)
        assert event["type"] == events.MOTION_DETECTED

    def test_allowed_on_a_development_install(self, client, sensor):
        with _debug_config(debug=False, environment="development"):
            response = client.post("/pir/trigger_test")
        assert response.status_code == 200

    def test_reports_failure_instead_of_raising(self, client, sensor):
        with _debug_config():
            with patch.object(
                routes_module, "motion_detected_sse", side_effect=RuntimeError("boom")
            ):
                response = client.post("/pir/trigger_test")
        assert response.status_code == 500


class TestMotionReachesTheBroker:
    """Motion must fan out through the shared broker in src/events.py."""

    def test_callback_publishes_a_motion_event(self, subscription):
        routes_module.motion_detected_sse()

        [event] = _drain(subscription)
        assert event["type"] == events.MOTION_DETECTED
        assert event["data"] == "Motion detected by PIR sensor"
        assert "timestamp" in event

    def test_the_callback_is_registered_with_the_sensor_module(self):
        assert routes_module.motion_detected_sse in sensor_module._motion_callbacks

    def test_sensor_motion_reaches_the_broker(self, sensor, subscription):
        sensor.start_monitoring()
        sensor._motion_detected()

        [event] = _drain(subscription)
        assert event["type"] == events.MOTION_DETECTED

    def test_debounced_motion_publishes_once(self, sensor, subscription):
        sensor.debounce_time = 60
        sensor._motion_detected()
        sensor._motion_detected()

        assert len(_drain(subscription)) == 1


class TestEventStream:
    """The legacy /pir/events endpoint is a motion-only view of the broker."""

    def test_stream_is_filtered_to_motion(self, client):
        stream = Mock(return_value=iter(["data: {}\n\n"]))
        with patch.object(broker, "stream", stream):
            response = client.get("/pir/events")
            body = response.get_data(as_text=True)

        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert body == "data: {}\n\n"
        assert stream.call_args.kwargs["only"] == (events.MOTION_DETECTED,)

    def test_stream_sets_the_sse_headers(self, client):
        with patch.object(broker, "stream", Mock(return_value=iter([]))):
            response = client.get("/pir/events")
            response.get_data()

        for header, value in events.sse_headers().items():
            assert response.headers[header] == value


class TestDiagnostics:
    """/pir/diagnostics returns the checks as JSON, or a generic 500."""

    def test_returns_the_check_results(self, client):
        with patch(
            "src.pir_sensor.diagnostics.run_all_checks",
            return_value={"issues": ["nothing plugged in"]},
        ):
            response = client.get("/pir/diagnostics")

        assert response.status_code == 200
        assert response.get_json() == {"issues": ["nothing plugged in"]}

    def test_failure_does_not_leak_details(self, client):
        with patch(
            "src.pir_sensor.diagnostics.run_all_checks",
            side_effect=RuntimeError("boom"),
        ):
            response = client.get("/pir/diagnostics")

        assert response.status_code == 500
        assert "boom" not in response.get_data(as_text=True)
