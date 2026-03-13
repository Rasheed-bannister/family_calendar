"""Tests for src/photo_upload/auth.py."""

import time

import pytest

from src.photo_upload.auth import RateLimiter, UploadTokenManager, generate_upload_url


@pytest.fixture
def token_manager():
    """Create a token manager with a known secret."""
    return UploadTokenManager(secret_key="test-secret-key", token_lifetime=3600)


class TestTokenGeneration:
    """Tests for token generation."""

    def test_generates_token(self, token_manager):
        result = token_manager.generate_token()
        assert "token" in result
        assert "expiry" in result
        assert "lifetime" in result
        assert result["lifetime"] == 3600

    def test_token_format(self, token_manager):
        result = token_manager.generate_token()
        token = result["token"]
        parts = token.split(".")
        assert len(parts) == 2  # token_id.signature

    def test_token_stored_in_active_tokens(self, token_manager):
        result = token_manager.generate_token()
        token_id = result["token"].split(".")[0]
        assert token_id in token_manager.active_tokens

    def test_token_with_ip(self, token_manager):
        result = token_manager.generate_token(ip_address="192.168.1.1")
        token_id = result["token"].split(".")[0]
        assert token_manager.active_tokens[token_id]["ip"] == "192.168.1.1"

    def test_unique_tokens(self, token_manager):
        t1 = token_manager.generate_token()
        t2 = token_manager.generate_token()
        assert t1["token"] != t2["token"]


class TestTokenValidation:
    """Tests for token validation."""

    def test_valid_token(self, token_manager):
        result = token_manager.generate_token()
        is_valid, error = token_manager.validate_token(result["token"])
        assert is_valid is True
        assert error is None

    def test_invalid_format(self, token_manager):
        is_valid, error = token_manager.validate_token("no-dot-here")
        assert is_valid is False
        assert "format" in error.lower()

    def test_unknown_token(self, token_manager):
        is_valid, error = token_manager.validate_token("unknown_id.fake_sig")
        assert is_valid is False

    def test_expired_token(self, token_manager):
        # Create a token with very short lifetime
        tm = UploadTokenManager(secret_key="test", token_lifetime=1)
        result = tm.generate_token()
        # Force expiry
        token_id = result["token"].split(".")[0]
        tm.active_tokens[token_id]["expiry"] = time.time() - 100

        is_valid, error = tm.validate_token(result["token"])
        assert is_valid is False
        assert "expired" in error.lower()

    def test_use_limit_exceeded(self, token_manager):
        result = token_manager.generate_token()
        token_id = result["token"].split(".")[0]
        token_manager.active_tokens[token_id]["max_uses"] = 2
        token_manager.active_tokens[token_id]["uses"] = 2

        is_valid, error = token_manager.validate_token(result["token"])
        assert is_valid is False
        assert "limit" in error.lower()

    def test_invalid_signature(self, token_manager):
        result = token_manager.generate_token()
        token_id = result["token"].split(".")[0]
        tampered = f"{token_id}.fakesignature"

        is_valid, error = token_manager.validate_token(tampered)
        assert is_valid is False
        assert "signature" in error.lower()

    def test_increments_use_count(self, token_manager):
        result = token_manager.generate_token()
        token_id = result["token"].split(".")[0]
        assert token_manager.active_tokens[token_id]["uses"] == 0

        token_manager.validate_token(result["token"])
        assert token_manager.active_tokens[token_id]["uses"] == 1


class TestTokenCleanup:
    """Tests for expired token cleanup."""

    def test_cleans_expired_on_generate(self, token_manager):
        # Create a token and manually expire it
        result = token_manager.generate_token()
        token_id = result["token"].split(".")[0]
        token_manager.active_tokens[token_id]["expiry"] = time.time() - 100

        # Generating a new token should clean up the expired one
        token_manager.generate_token()
        assert token_id not in token_manager.active_tokens


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_allows_first_request(self):
        limiter = RateLimiter()
        is_allowed, error = limiter.is_allowed("test-client")
        assert is_allowed is True
        assert error is None

    def test_blocks_over_minute_limit(self):
        limiter = RateLimiter()
        identifier = "test-client"
        for i in range(limiter.upload_limits["per_minute"]):
            is_allowed, _ = limiter.is_allowed(identifier)
            assert is_allowed is True

        # Next request should be blocked
        is_allowed, error = limiter.is_allowed(identifier)
        assert is_allowed is False
        assert "minute" in error.lower()

    def test_different_clients_independent(self):
        limiter = RateLimiter()
        # Exhaust limit for client A
        for i in range(limiter.upload_limits["per_minute"]):
            limiter.is_allowed("client-a")

        # Client B should still be allowed
        is_allowed, _ = limiter.is_allowed("client-b")
        assert is_allowed is True

    def test_records_requests(self):
        limiter = RateLimiter()
        limiter.is_allowed("test-client")
        assert len(limiter.requests["test-client"]) == 1


class TestGenerateUploadUrl:
    """Tests for generate_upload_url."""

    def test_basic_url(self):
        url = generate_upload_url("http://example.com/upload", "abc123")
        assert url == "http://example.com/upload?token=abc123"
