"""Tests for the /api/display endpoints."""

import pytest

from src.display.service import get_display_service, set_display_service
from src.main import create_app


class FakeService:
    def __init__(self):
        self.calls = []
        self.mode = "active"

    def snapshot(self):
        return {"mode": self.mode, "brightness": 1.0, "overlay_brightness": 1.0}

    def activity(self, source):
        self.calls.append(("activity", source))
        self.mode = "active"
        return self.snapshot()

    def force_slideshow(self):
        self.calls.append(("sleep", None))
        self.mode = "slideshow"
        return self.snapshot()


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def service():
    saved = get_display_service()
    fake = FakeService()
    set_display_service(fake)
    yield fake
    set_display_service(saved)


def test_get_returns_snapshot(client, service):
    response = client.get("/api/display")
    assert response.status_code == 200
    assert response.get_json()["mode"] == "active"


def test_activity_records_known_source(client, service):
    response = client.post("/api/display/activity", json={"source": "touch"})
    assert response.status_code == 200
    assert service.calls == [("activity", "touch")]


@pytest.mark.parametrize("body", [{"source": "<script>"}, {}, None])
def test_unknown_or_missing_source_becomes_browser(client, service, body):
    if body is None:
        response = client.post("/api/display/activity")
    else:
        response = client.post("/api/display/activity", json=body)
    assert response.status_code == 200
    assert service.calls == [("activity", "browser")]


def test_sleep_forces_slideshow(client, service):
    response = client.post("/api/display/sleep")
    assert response.status_code == 200
    assert response.get_json()["mode"] == "slideshow"
    assert service.calls == [("sleep", None)]


def test_get_rejects_post(client, service):
    assert client.post("/api/display").status_code == 405


def test_endpoints_build_a_real_service_when_none_installed(client):
    saved = get_display_service()
    set_display_service(None)
    try:
        data = client.get("/api/display").get_json()
        assert data["mode"] == "active"
        assert "thresholds" in data
        built = get_display_service()
        assert built is not None
        assert built.running is False  # a request must not start the ticker
    finally:
        set_display_service(saved)
