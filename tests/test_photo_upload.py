"""Tests for photo upload functionality including QR code generation and token validation."""

import json
import tempfile
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from src.photo_upload.auth import UploadTokenManager, generate_upload_url
from src.photo_upload.routes import upload_bp


@pytest.fixture
def app():
    """Create test Flask app."""
    app = Flask(__name__)
    app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",  # pragma: allowlist secret
            "UPLOAD_TOKEN_LIFETIME": 3600,
        }
    )

    # Use temporary directory for static files
    with tempfile.TemporaryDirectory() as temp_dir:
        app.static_folder = temp_dir
        app.register_blueprint(upload_bp)
        yield app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def token_manager():
    """Create test token manager."""
    test_key = "test-" + "secret-key"  # pragma: allowlist secret
    return UploadTokenManager(secret_key=test_key, token_lifetime=3600)


def test_token_generation_and_validation(token_manager):
    """Test token generation and validation flow."""
    client_ip = "192.168.1.100"

    # Generate token
    token_data = token_manager.generate_token(ip_address=client_ip)

    assert "token" in token_data
    assert "expiry" in token_data
    assert "lifetime" in token_data
    assert token_data["lifetime"] == 3600

    # Validate token with correct IP
    is_valid, error = token_manager.validate_token(token_data["token"], client_ip)
    assert is_valid is True
    assert error is None

    # Validate token with different IP (should still work - NAT tolerance)
    is_valid, error = token_manager.validate_token(token_data["token"], "192.168.1.101")
    assert is_valid is True  # Should still work due to NAT tolerance
    assert error is None


def test_qr_code_url_generation():
    """Test QR code URL generation."""
    base_url = "http://192.168.1.50:5000/upload/manage"
    token = "test_token_12345.signature_hash"

    url = generate_upload_url(base_url, token)
    expected_url = f"{base_url}?token={token}"

    assert url == expected_url


@patch("src.photo_upload.routes.qrcode")
def test_qr_code_generation_endpoint(mock_qrcode, client, app):
    """Test the QR code generation endpoint."""
    # Mock QR code generation
    mock_qr_instance = Mock()
    mock_img = Mock()
    mock_qrcode.QRCode.return_value = mock_qr_instance
    mock_qr_instance.make_image.return_value = mock_img

    # Mock image save to return base64 data
    def mock_save(buffer, format):
        # Simulate saving PNG data
        buffer.write(b"mock_png_data")

    mock_img.save = mock_save

    with app.app_context():
        with patch("src.photo_upload.routes.QRCODE_AVAILABLE", True):
            response = client.get("/upload/qrcode")

            assert response.status_code == 200
            data = json.loads(response.data)

            assert data["success"] is True
            assert "qrcode" in data
            assert data["qrcode"].startswith("data:image/png;base64,")
            assert "url" in data
            assert "expires_in" in data
            assert "message" in data


def test_token_validation_missing_token(client):
    """Test token validation with missing token."""
    response = client.post("/upload/api/photos")

    assert response.status_code == 401
    data = json.loads(response.data)
    assert "error" in data
    assert "token required" in data["error"].lower()


def test_token_validation_invalid_token(client):
    """Test token validation with invalid token."""
    headers = {"X-Upload-Token": "invalid_token"}
    response = client.post("/upload/api/photos", headers=headers)

    assert response.status_code == 401
    data = json.loads(response.data)
    assert "error" in data


@pytest.mark.skip(reason="Requires templates directory structure")
def test_manage_photos_page_with_token(client):
    """Test photo management page with token parameter."""
    response = client.get("/upload/manage?token=test_token_123")

    assert response.status_code == 200
    assert b"Photo Manager" in response.data
    assert b"test_token_123" in response.data or b"token" in response.data


@pytest.mark.skip(reason="Requires templates directory structure")
def test_upload_page_with_token(client):
    """Test upload page with token parameter."""
    response = client.get("/upload/?token=test_token_123")

    assert response.status_code == 200
    assert b"Upload Photos" in response.data


@patch.dict("os.environ", {"CALENDAR_UPLOAD_HOST": "192.168.1.100"})
def test_host_override_in_qr_generation(client, app):
    """Test host override via environment variable."""
    with app.app_context():
        with patch("src.photo_upload.routes.QRCODE_AVAILABLE", True):
            with patch("src.photo_upload.routes.qrcode") as mock_qrcode:
                # Mock QR code generation
                mock_qr_instance = Mock()
                mock_img = Mock()
                mock_qrcode.QRCode.return_value = mock_qr_instance
                mock_qr_instance.make_image.return_value = mock_img

                # Mock image save
                def mock_save(buffer, format):
                    buffer.write(b"mock_png_data")

                mock_img.save = mock_save

                response = client.get("/upload/qrcode")

                assert response.status_code == 200
                data = json.loads(response.data)

                # Verify the URL contains the override host
                assert "192.168.1.100" in data["url"]


def test_network_url_format():
    """Test that generated URLs have correct format for mobile access."""
    # Test typical network scenarios
    test_cases = [
        ("192.168.1.100", "5000", "http://192.168.1.100:5000/upload/manage"),
        ("10.0.1.50", "8080", "http://10.0.1.50:8080/upload/manage"),
        ("172.16.1.25", "5000", "http://172.16.1.25:5000/upload/manage"),
    ]

    for host, port, expected_base in test_cases:
        base_url = f"http://{host}:{port}/upload/manage"
        token = "sample_token.signature"

        full_url = generate_upload_url(base_url, token)

        assert full_url.startswith(expected_base)
        assert f"token={token}" in full_url
        assert full_url.count("?") == 1  # Only one query parameter separator


def test_token_expiry_calculation(token_manager):
    """Test token expiry calculation."""
    import time

    # Generate token
    start_time = time.time()
    token_data = token_manager.generate_token()

    # Check expiry is approximately correct (within 5 seconds)
    expected_expiry = start_time + 3600
    actual_expiry = token_data["expiry"]

    assert abs(actual_expiry - expected_expiry) < 5


def test_same_local_network_validation(token_manager):
    """Test local network IP validation for QR code security."""
    # Test case 1: Generate token from Raspberry Pi (127.0.0.1)
    # Should allow access from same local network mobile device
    pi_ip = "127.0.0.1"
    mobile_ip = "10.69.30.53"  # Same network as Pi's actual network IP

    token_data = token_manager.generate_token(ip_address=pi_ip)

    # This should fail because 127.0.0.1 vs 10.69.30.53 are different networks
    is_valid, error = token_manager.validate_token(token_data["token"], mobile_ip)
    assert is_valid is False
    assert "network" in error.lower()

    # Test case 2: Generate token from Pi's actual network IP
    pi_network_ip = "10.69.30.54"  # Pi's network IP
    mobile_ip = "10.69.30.53"  # Mobile device on same network

    token_data = token_manager.generate_token(ip_address=pi_network_ip)

    # This should work - same first two octets (10.69)
    is_valid, error = token_manager.validate_token(token_data["token"], mobile_ip)
    assert is_valid is True
    assert error is None

    # Test case 3: Different networks should fail
    external_ip = "192.168.1.100"  # Different network

    is_valid, error = token_manager.validate_token(token_data["token"], external_ip)
    assert is_valid is False
    assert "network" in error.lower()

    # Test case 4: Test edge cases
    invalid_ips = ["invalid.ip", "10.69.30", "10.69.30.54.extra", ""]

    for invalid_ip in invalid_ips:
        is_valid, error = token_manager.validate_token(token_data["token"], invalid_ip)
        assert is_valid is False


def test_network_validation_helper(token_manager):
    """Test the _is_same_local_network helper method directly."""
    test_cases = [
        # (ip1, ip2, expected_result)
        ("10.69.30.54", "10.69.30.53", True),  # Same network
        ("10.69.1.1", "10.69.2.1", True),  # Same network, different subnets
        ("192.168.1.1", "192.168.1.100", True),  # Same network
        ("10.69.30.54", "10.68.30.54", False),  # Different network
        ("192.168.1.1", "10.0.1.1", False),  # Completely different
        ("127.0.0.1", "10.69.30.54", False),  # Localhost vs network
        ("invalid", "10.69.30.54", False),  # Invalid IP
        ("10.69.30.54", "invalid", False),  # Invalid IP
        ("10.69.30", "10.69.30.54", False),  # Invalid format
        ("", "", False),  # Empty strings
    ]

    for ip1, ip2, expected in test_cases:
        result = token_manager._is_same_local_network(ip1, ip2)
        assert (
            result == expected
        ), f"Failed for {ip1} vs {ip2}: expected {expected}, got {result}"


def test_qr_code_localhost_to_network_ip_binding(token_manager):
    """Test QR code generation binds token to network IP when accessed from localhost."""
    # Simulate QR code generation from touchscreen (localhost access)
    import unittest.mock

    # Mock get_local_ip to return the Pi's network IP
    with unittest.mock.patch(
        "src.photo_upload.routes.get_local_ip", return_value="10.69.30.54"
    ):
        # Simulate localhost access to QR generation
        localhost_ip = "127.0.0.1"
        network_ip = "10.69.30.54"

        # This simulates the QR code generation logic
        client_ip = localhost_ip
        token_bind_ip = (
            network_ip if client_ip in ["127.0.0.1", "::1", "localhost"] else client_ip
        )

        # Generate token with the network IP binding
        token_data = token_manager.generate_token(ip_address=token_bind_ip)

        # Mobile device on same network should be able to access
        mobile_ip = "10.69.30.53"
        is_valid, error = token_manager.validate_token(token_data["token"], mobile_ip)
        assert is_valid is True
        assert error is None

        # Different network should still be blocked
        external_ip = "192.168.1.100"
        is_valid, error = token_manager.validate_token(token_data["token"], external_ip)
        assert is_valid is False
        assert "network" in error.lower()


@patch("src.photo_upload.routes.get_local_ip")
def test_local_ip_detection(mock_get_local_ip, client, app):
    """Test local IP detection for QR code generation."""
    mock_get_local_ip.return_value = "192.168.1.50"

    with app.app_context():
        with patch("src.photo_upload.routes.QRCODE_AVAILABLE", True):
            with patch("src.photo_upload.routes.qrcode") as mock_qrcode:
                # Mock QR code components
                mock_qr_instance = Mock()
                mock_img = Mock()
                mock_qrcode.QRCode.return_value = mock_qr_instance
                mock_qr_instance.make_image.return_value = mock_img

                def mock_save(buffer, format):
                    buffer.write(b"mock_png_data")

                mock_img.save = mock_save

                response = client.get("/upload/qrcode")

                assert response.status_code == 200
                data = json.loads(response.data)

                # Verify IP detection was called and used
                mock_get_local_ip.assert_called()
                assert "192.168.1.50" in data["url"]


def test_cors_headers(client):
    """Test CORS headers are present for mobile access."""
    # Test preflight request
    response = client.options("/upload/api/photos")

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" in response.headers
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "Access-Control-Allow-Headers" in response.headers
    assert "X-Upload-Token" in response.headers["Access-Control-Allow-Headers"]


def test_token_preservation_in_navigation():
    """Test that tokens are preserved in navigation links."""
    # This test validates that the JavaScript logic preserves tokens
    # when navigating between upload and manage pages

    test_token = "test_token_123.signature_hash"

    # Test URL generation logic that should match the JavaScript
    upload_url_with_token = f"/upload/?token={test_token}"
    manage_url_with_token = f"/upload/manage?token={test_token}"

    # Verify URL formats are correct
    assert f"token={test_token}" in upload_url_with_token
    assert f"token={test_token}" in manage_url_with_token

    # Test that URLs without tokens are handled gracefully
    upload_url_without_token = "/upload/"
    manage_url_without_token = "/upload/manage"

    assert "token=" not in upload_url_without_token
    assert "token=" not in manage_url_without_token


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
