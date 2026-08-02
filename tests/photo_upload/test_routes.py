"""Tests for src/photo_upload/routes.py."""

import io
import logging
from unittest.mock import patch

import pytest
from PIL import Image

from src.main import create_app
from src.photo_upload import auth as auth_module
from src.photo_upload.routes import (
    MAX_FILE_SIZE,
    MAX_FILES_PER_REQUEST,
    MAX_PER_PAGE,
    MAX_UPLOAD_CONTENT_LENGTH,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Keep the module-global rate limiter from leaking between tests."""
    auth_module.rate_limiter.requests.clear()
    yield
    auth_module.rate_limiter.requests.clear()


@pytest.fixture
def app(tmp_path):
    """Create the app with an isolated static folder for photo writes."""
    app = create_app()
    app.config["TESTING"] = True
    app.static_folder = str(tmp_path)
    return app


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    with app.test_client() as client:
        with app.app_context():
            pass
        yield client


@pytest.fixture
def token(app):
    """Issue a valid upload token from the app's token manager."""
    assert auth_module.token_manager is not None
    return auth_module.token_manager.generate_token()["token"]


def _png_bytes(size=(4, 4)):
    """Return the bytes of a tiny valid PNG."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(120, 60, 30)).save(buffer, "PNG")
    buffer.seek(0)
    return buffer.getvalue()


class TestUploadSizeLimit:
    """MAX_CONTENT_LENGTH must be enforced at the request boundary."""

    def test_max_content_length_is_configured(self, app):
        assert app.config["MAX_CONTENT_LENGTH"] == MAX_UPLOAD_CONTENT_LENGTH

    def test_limit_covers_a_full_multi_file_batch(self, app):
        """A legitimate max-size batch must not be rejected by the app cap."""
        assert app.config["MAX_CONTENT_LENGTH"] >= MAX_FILE_SIZE * MAX_FILES_PER_REQUEST

    def test_oversized_request_returns_json_not_html(self, app, client, token):
        app.config["MAX_CONTENT_LENGTH"] = 1024

        response = client.post(
            "/upload/api/photos",
            data={
                "token": token,
                "photos": (io.BytesIO(b"x" * 8192), "big.jpg"),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 413
        assert response.content_type.startswith("application/json")
        assert "error" in response.get_json()

    def test_oversized_request_rejected_before_the_handler_runs(self, app, client):
        """The body is refused at the boundary, not after buffering it."""
        app.config["MAX_CONTENT_LENGTH"] = 1024

        # No token at all: a 401 would mean the request body was read and
        # dispatched first. A 413 means Werkzeug cut it off up front.
        response = client.post(
            "/upload/api/photos",
            data={"photos": (io.BytesIO(b"x" * 8192), "big.jpg")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 413
        assert response.content_type.startswith("application/json")

    def test_request_within_limit_still_works(self, app, client, token):
        app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

        with patch("src.photo_upload.routes.slideshow_db"):
            response = client.post(
                "/upload/api/photos",
                data={
                    "token": token,
                    "photos": (io.BytesIO(_png_bytes()), "small.png"),
                },
                content_type="multipart/form-data",
            )

        assert response.status_code == 200
        assert response.get_json()["count"] == 1


class TestUploadLogging:
    """No token material may reach the log during a real upload."""

    def test_token_not_logged_on_successful_upload(self, client, token, caplog):
        caplog.set_level(logging.DEBUG)

        with patch("src.photo_upload.routes.slideshow_db"):
            response = client.post(
                "/upload/api/photos",
                data={
                    "token": token,
                    "photos": (io.BytesIO(_png_bytes()), "holiday.png"),
                },
                content_type="multipart/form-data",
            )

        assert response.status_code == 200

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert token not in logged
        assert token.split(".")[0] not in logged
        assert token[:20] not in logged

    def test_form_fields_are_not_dumped(self, client, token, caplog):
        """A whole-form dump is what leaked the token; it must be gone."""
        caplog.set_level(logging.DEBUG)

        with patch("src.photo_upload.routes.slideshow_db"):
            client.post(
                "/upload/api/photos",
                data={
                    "token": token,
                    "caption": "a-distinctive-form-value",
                    "photos": (io.BytesIO(_png_bytes()), "holiday.png"),
                },
                content_type="multipart/form-data",
            )

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert "a-distinctive-form-value" not in logged

    def test_page_views_do_not_log_query_string(self, client, token, caplog):
        """The QR flow puts the token in the URL of both HTML pages."""
        caplog.set_level(logging.DEBUG)

        client.get(f"/upload/?token={token}")
        client.get(f"/upload/manage?token={token}")

        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert token not in logged
        assert token[:20] not in logged


class TestListPhotosAuth:
    """Reading the photo list requires the same token as writing."""

    def test_requires_token(self, client):
        response = client.get("/upload/api/photos")
        assert response.status_code == 401
        assert "error" in response.get_json()

    def test_no_filenames_leak_without_token(self, client, tmp_path):
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        (photos_dir / "private_photo.jpg").write_bytes(_png_bytes())

        response = client.get("/upload/api/photos")
        assert response.status_code == 401
        assert "private_photo" not in response.get_data(as_text=True)

    def test_accepts_query_token(self, client, token):
        """photo_manage.html's loadPhotos() appends ?token=... to this call."""
        response = client.get(f"/upload/api/photos?token={token}")
        assert response.status_code == 200
        assert "photos" in response.get_json()

    def test_accepts_header_token(self, client, token):
        response = client.get("/upload/api/photos", headers={"X-Upload-Token": token})
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/upload/api/photos"),
            ("post", "/upload/api/photos"),
            ("delete", "/upload/api/photos/some.jpg"),
        ],
    )
    def test_read_and_write_have_the_same_auth_story(self, client, method, path):
        response = getattr(client, method)(path)
        assert response.status_code == 401

    def test_lists_photos_present_on_disk(self, client, token, tmp_path):
        photos_dir = tmp_path / "photos"
        photos_dir.mkdir()
        (photos_dir / "one.jpg").write_bytes(_png_bytes())
        (photos_dir / "two.jpg").write_bytes(_png_bytes())

        data = client.get(f"/upload/api/photos?token={token}").get_json()
        assert data["total"] == 2
        assert {photo["filename"] for photo in data["photos"]} == {
            "one.jpg",
            "two.jpg",
        }


class TestListPhotosPagination:
    """Malformed pagination must not turn into a 500."""

    @pytest.fixture
    def photos_dir(self, tmp_path):
        directory = tmp_path / "photos"
        directory.mkdir()
        for index in range(5):
            (directory / f"photo_{index}.jpg").write_bytes(_png_bytes())
        return directory

    def test_per_page_zero_does_not_500(self, client, token, photos_dir):
        response = client.get(f"/upload/api/photos?token={token}&per_page=0")
        assert response.status_code == 200
        data = response.get_json()
        assert data["per_page"] == 1
        assert data["pages"] == 5

    def test_negative_per_page_is_clamped(self, client, token, photos_dir):
        response = client.get(f"/upload/api/photos?token={token}&per_page=-10")
        assert response.status_code == 200
        assert response.get_json()["per_page"] == 1

    def test_negative_page_is_clamped(self, client, token, photos_dir):
        response = client.get(f"/upload/api/photos?token={token}&page=-3")
        assert response.status_code == 200
        data = response.get_json()
        assert data["page"] == 1
        assert len(data["photos"]) == 5

    def test_zero_page_is_clamped(self, client, token, photos_dir):
        response = client.get(f"/upload/api/photos?token={token}&page=0")
        assert response.status_code == 200
        assert response.get_json()["page"] == 1

    def test_per_page_above_max_is_clamped(self, client, token, photos_dir):
        response = client.get(f"/upload/api/photos?token={token}&per_page=100000")
        assert response.status_code == 200
        assert response.get_json()["per_page"] == MAX_PER_PAGE

    @pytest.mark.parametrize(
        "query",
        [
            "per_page=abc",
            "page=abc",
            "page=1.5",
            "per_page=",
            "page=",
            "per_page=1e9",
        ],
    )
    def test_non_integer_values_return_400(self, client, token, query):
        response = client.get(f"/upload/api/photos?token={token}&{query}")
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_defaults_when_unspecified(self, client, token, photos_dir):
        data = client.get(f"/upload/api/photos?token={token}").get_json()
        assert data["page"] == 1
        assert data["per_page"] == 20

    def test_page_past_the_end_is_empty_not_an_error(self, client, token, photos_dir):
        data = client.get(
            f"/upload/api/photos?token={token}&page=99&per_page=2"
        ).get_json()
        assert data["photos"] == []
        assert data["total"] == 5


class TestQrCodeTokenMinting:
    """/upload/qrcode mints a live upload token on every call.

    It cannot require a token (it is how a phone gets its first one), so the
    rate limit is the only thing bounding the token table. Without it, any LAN
    client could grow that table without limit on a Raspberry Pi.
    """

    def test_qrcode_minting_is_rate_limited(self, client):
        from src.photo_upload import auth as auth_module

        before = len(auth_module.token_manager.active_tokens)
        statuses = [client.get("/upload/qrcode").status_code for _ in range(200)]
        minted = len(auth_module.token_manager.active_tokens) - before

        allowed = statuses.count(200)
        assert 429 in statuses, "unbounded token minting is possible"
        assert minted == allowed, "a token was minted without a 200 response"
        assert minted <= auth_module.rate_limiter.upload_limits["per_minute"]

    def test_a_normal_single_request_still_works(self, client):
        """The UI fetches this on a button press; it must not be throttled."""
        response = client.get("/upload/qrcode")
        assert response.status_code == 200
        assert response.get_json()["success"] is True
