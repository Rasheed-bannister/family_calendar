"""Regression tests for CodeQL py/stack-trace-exposure fixes.

A handler that catches an exception must log it and return a fixed message.
Raw exception text can carry filesystem paths, SQL, or library internals,
and some of these endpoints are reachable from any phone holding an upload
token. Each test injects a failure whose message contains a sentinel and
asserts the sentinel never appears in the response body.
"""

import io
from unittest.mock import patch

import pytest

from src.health_monitor import health_monitor
from src.main import create_app

SENTINEL = "internal detail that must not leak"


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _assert_no_leak(response):
    body = response.get_data(as_text=True)
    assert SENTINEL not in body, body


@pytest.mark.parametrize(
    "path, method, target",
    [
        ("/health/", "get", "check_health"),
        ("/health/detailed", "get", "check_health"),
        ("/health/system", "get", "get_system_info"),
        ("/health/databases", "get", "get_database_status"),
        ("/health/errors", "get", "should_restart"),
        ("/health/monitoring/enable", "post", "enable_monitoring"),
        ("/health/monitoring/disable", "post", "disable_monitoring"),
    ],
)
def test_health_routes_do_not_return_exception_text(client, path, method, target):
    with patch.object(health_monitor, target, side_effect=RuntimeError(SENTINEL)):
        response = getattr(client, method)(path)
    assert response.status_code == 500
    _assert_no_leak(response)


def test_chores_refresh_does_not_return_exception_text(client):
    with patch(
        "src.google_integration.routes.start_tasks_sync",
        side_effect=RuntimeError(SENTINEL),
    ):
        response = client.post("/chores/refresh")
    assert response.status_code == 500
    assert response.get_json() == {"error": "Chores refresh failed"}


def test_add_chore_does_not_return_exception_text(client):
    with patch(
        "src.chores_app.routes.db.add_chore", side_effect=RuntimeError(SENTINEL)
    ):
        response = client.post("/chores/add", json={"title": "Kid", "notes": "Dishes"})
    assert response.status_code == 500
    _assert_no_leak(response)


def test_photo_upload_error_does_not_return_exception_text(client):
    """The phone gets "Failed to save <name>", never the exception text.

    The token and rate-limit decorators are covered by tests/photo_upload, so
    the handler is called through ``__wrapped__`` inside a request context.
    Saving is mocked and optimisation raises, so nothing is written to disk.
    """
    app = client.application
    view = app.view_functions["upload.upload_photos"]
    handler = view.__wrapped__.__wrapped__

    with (
        patch("werkzeug.datastructures.FileStorage.save"),
        patch("src.photo_upload.routes.optimize_image", side_effect=OSError(SENTINEL)),
        patch("src.photo_upload.routes.slideshow_db.sync_photos"),
        app.test_request_context(
            "/upload/api/photos",
            method="POST",
            data={"photos": (io.BytesIO(b"\xff\xd8\xff fake jpeg"), "a.jpg")},
            content_type="multipart/form-data",
        ),
    ):
        response = app.make_response(handler())

    _assert_no_leak(response)
    assert "Failed to save a.jpg" in response.get_json()["errors"]
