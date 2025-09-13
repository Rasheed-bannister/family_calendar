"""
Authentication and security for photo upload feature.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from flask import jsonify, request

logger = logging.getLogger(__name__)


class UploadTokenManager:
    """Manages secure tokens for photo upload access."""

    def __init__(self, secret_key=None, token_lifetime=3600):
        """
        Initialize the token manager.

        Args:
            secret_key: Secret key for HMAC signatures (will generate if not provided)
            token_lifetime: Token lifetime in seconds (default: 1 hour)
        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self.token_lifetime = token_lifetime
        self.active_tokens = {}  # Store active tokens with metadata

    def generate_token(self, ip_address=None):
        """
        Generate a new secure upload token.

        Args:
            ip_address: Optional IP address to bind the token to

        Returns:
            dict: Token data including the token string and expiry
        """
        # Generate random token
        token_id = secrets.token_urlsafe(32)
        timestamp = int(time.time())
        expiry = timestamp + self.token_lifetime

        # Create token payload
        payload = {
            "id": token_id,
            "created": timestamp,
            "expiry": expiry,
            "ip": ip_address,
        }

        # Create HMAC signature
        signature = self._create_signature(payload)

        # Combine token and signature
        token = f"{token_id}.{signature}"

        # Store token metadata
        self.active_tokens[token_id] = {
            "created": timestamp,
            "expiry": expiry,
            "ip": ip_address,
            "uses": 0,
            "max_uses": 100,  # Limit uses per token
        }

        # Clean up expired tokens
        self._cleanup_expired_tokens()

        return {"token": token, "expiry": expiry, "lifetime": self.token_lifetime}

    def validate_token(self, token, ip_address=None):
        """
        Validate an upload token.

        Args:
            token: The token string to validate
            ip_address: Optional IP address to verify against

        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            # Split token and signature
            parts = token.split(".")
            if len(parts) != 2:
                return False, "Invalid token format"

            token_id, signature = parts

            # Check if token exists and is not expired
            if token_id not in self.active_tokens:
                return False, "Token not found or expired"

            token_data = self.active_tokens[token_id]

            # Check expiry
            if time.time() > token_data["expiry"]:
                del self.active_tokens[token_id]
                return False, "Token expired"

            # Check use count
            if token_data["uses"] >= token_data["max_uses"]:
                return False, "Token use limit exceeded"

            # Verify IP if provided
            if ip_address and token_data.get("ip"):
                if ip_address != token_data["ip"]:
                    logger.warning(
                        f"IP mismatch for token: expected {token_data['ip']}, got {ip_address}"
                    )
                    # Don't fail on IP mismatch, just log it (for NAT scenarios)

            # Verify signature
            expected_payload = {
                "id": token_id,
                "created": token_data["created"],
                "expiry": token_data["expiry"],
                "ip": token_data.get("ip"),
            }

            expected_signature = self._create_signature(expected_payload)
            if not hmac.compare_digest(signature, expected_signature):
                return False, "Invalid token signature"

            # Increment use count
            token_data["uses"] += 1

            return True, None

        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False, "Token validation failed"

    def revoke_token(self, token):
        """Revoke a token immediately."""
        try:
            token_id = token.split(".")[0]
            if token_id in self.active_tokens:
                del self.active_tokens[token_id]
                return True
        except (KeyError, ValueError, TypeError):
            pass
        return False

    def _create_signature(self, payload):
        """Create HMAC signature for a payload."""
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hmac.new(
            self.secret_key.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()
        return signature

    def _cleanup_expired_tokens(self):
        """Remove expired tokens from memory."""
        current_time = time.time()
        expired = [
            token_id
            for token_id, data in self.active_tokens.items()
            if current_time > data["expiry"]
        ]
        for token_id in expired:
            del self.active_tokens[token_id]

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired tokens")


# Global token manager instance
token_manager = None


def init_token_manager(app):
    """Initialize the global token manager with app config."""
    global token_manager

    secret_key = app.config.get("SECRET_KEY", secrets.token_hex(32))
    token_lifetime = app.config.get("UPLOAD_TOKEN_LIFETIME", 3600)  # 1 hour default

    token_manager = UploadTokenManager(
        secret_key=secret_key, token_lifetime=token_lifetime
    )

    logger.info(
        f"Upload token manager initialized with {token_lifetime}s token lifetime"
    )
    return token_manager


def require_upload_token(f):
    """
    Decorator to require a valid upload token for a route.

    The token can be provided in:
    - Query parameter: ?token=xxx
    - Header: X-Upload-Token: xxx
    - Form data: token=xxx
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get token from various sources
        token_from_args = request.args.get("token")
        token_from_headers = request.headers.get("X-Upload-Token")
        token_from_form = request.form.get("token")

        token = token_from_args or token_from_headers or token_from_form

        logger.info(f"Token validation attempt from {request.remote_addr}")
        logger.info(f"Token from args: {'Yes' if token_from_args else 'No'}")
        logger.info(f"Token from headers: {'Yes' if token_from_headers else 'No'}")
        logger.info(f"Token from form: {'Yes' if token_from_form else 'No'}")
        logger.info(f"Final token: {'Yes' if token else 'No'}")
        if token:
            logger.info(f"Token preview: {token[:20]}...")

        if not token:
            logger.warning(f"No token provided from {request.remote_addr}")
            return jsonify({"error": "Upload token required"}), 401

        # Get client IP
        client_ip = request.remote_addr

        # Ensure token manager is initialized
        global token_manager
        if token_manager is None:
            from flask import current_app

            token_manager = init_token_manager(current_app)

        # Validate token
        is_valid, error = token_manager.validate_token(token, client_ip)

        if not is_valid:
            logger.warning(f"Invalid token attempt from {client_ip}: {error}")
            return jsonify({"error": error or "Invalid token"}), 401

        # Token is valid, proceed with the request
        return f(*args, **kwargs)

    return decorated_function


def generate_upload_url(base_url, token):
    """Generate a secure upload URL with embedded token."""
    return f"{base_url}?token={token}"


class RateLimiter:
    """Simple rate limiter for upload endpoints."""

    def __init__(self):
        self.requests = defaultdict(list)
        self.upload_limits = {
            "per_minute": 10,
            "per_hour": 100,
            "max_file_size": 16 * 1024 * 1024,  # 16MB
            "max_files_per_request": 10,
        }

    def is_allowed(self, identifier):
        """Check if a request is allowed based on rate limits."""
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)

        # Clean old entries
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier] if req_time > hour_ago
        ]

        # Count requests in windows
        minute_requests = sum(
            1 for req_time in self.requests[identifier] if req_time > minute_ago
        )
        hour_requests = len(self.requests[identifier])

        # Check limits
        if minute_requests >= self.upload_limits["per_minute"]:
            return False, "Rate limit exceeded: too many requests per minute"

        if hour_requests >= self.upload_limits["per_hour"]:
            return False, "Rate limit exceeded: too many requests per hour"

        # Record this request
        self.requests[identifier].append(now)

        return True, None


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limit_upload(f):
    """Decorator to apply rate limiting to upload endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Use token or IP as identifier
        identifier = (
            request.args.get("token")
            or request.headers.get("X-Upload-Token")
            or request.remote_addr
        )

        is_allowed, error = rate_limiter.is_allowed(identifier)

        if not is_allowed:
            logger.warning(f"Rate limit exceeded for {identifier}: {error}")
            return jsonify({"error": error}), 429  # Too Many Requests

        return f(*args, **kwargs)

    return decorated_function
