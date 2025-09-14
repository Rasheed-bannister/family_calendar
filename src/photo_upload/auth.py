"""Authentication and security for photo upload feature."""

import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import wraps
from typing import Any

from flask import Flask, Response, current_app, jsonify, request

# Constants
TOKEN_PARTS_COUNT = 2

# Type alias for Flask route return types
FlaskRouteReturn = Response | tuple[Response, int] | str

logger = logging.getLogger(__name__)


class UploadTokenManager:
    """Manages secure tokens for photo upload access."""

    def __init__(
        self,
        secret_key: str | None = None,
        token_lifetime: int = 3600,
    ) -> None:
        """Initialize the token manager.

        Args:
            secret_key: Secret key for HMAC signatures (will generate if not provided)
            token_lifetime: Token lifetime in seconds (default: 1 hour)

        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self.token_lifetime = token_lifetime
        self.active_tokens: dict[str, dict[str, Any]] = (
            {}
        )  # Store active tokens with metadata

    def generate_token(self, ip_address: str | None = None) -> dict[str, Any]:
        """Generate a new secure upload token.

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

    def validate_token(
        self,
        token: str,
        ip_address: str | None = None,
    ) -> tuple[bool, str | None]:
        """Validate an upload token.

        Args:
            token: The token string to validate
            ip_address: Optional IP address to verify against

        Returns:
            tuple: (is_valid, error_message)

        """
        try:
            # Split token and signature
            parts = token.split(".")
            if len(parts) != TOKEN_PARTS_COUNT:
                return False, "Invalid token format"

            token_id, signature = parts

            # Check if token exists
            if token_id not in self.active_tokens:
                return False, "Token not found or expired"

            token_data = self.active_tokens[token_id]

            # Validate token conditions
            error_message = self._validate_token_conditions(
                token_id,
                token_data,
                ip_address,
            )
            if error_message:
                return False, error_message

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
        except Exception:
            logger.exception("Token validation error")
            return False, "Token validation failed"
        else:
            return True, None

    def _validate_token_conditions(
        self,
        token_id: str,
        token_data: dict[str, Any],
        ip_address: str | None,
    ) -> str | None:
        """Validate token expiry, usage limits, and IP if applicable."""
        # Check expiry
        if time.time() > token_data["expiry"]:
            del self.active_tokens[token_id]
            return "Token expired"

        # Check use count
        if token_data["uses"] >= token_data["max_uses"]:
            return "Token use limit exceeded"

        # Verify IP if token was bound to an IP - allow same local network (first two octets)
        if token_data.get("ip"):
            if not ip_address:
                return "Invalid client IP address"
            if not self._is_same_local_network(token_data["ip"], ip_address):
                logger.warning(
                    "IP network mismatch for token: expected network %s, got %s",
                    token_data["ip"],
                    ip_address,
                )
                return "Token not valid for this network"

        return None

    def _is_same_local_network(self, ip1: str, ip2: str) -> bool:
        """Check if two IP addresses are on the same local network (same first two octets)."""
        try:
            # Split IPs and compare first two octets
            octets1 = ip1.split(".")
            octets2 = ip2.split(".")

            # Both must be valid IPv4 addresses (4 octets)
            if len(octets1) != 4 or len(octets2) != 4:
                return False

            # Compare first two octets for local network match
            return octets1[0] == octets2[0] and octets1[1] == octets2[1]
        except (AttributeError, IndexError, ValueError):
            # If IP parsing fails, deny access for security
            return False

    def revoke_token(self, token: str) -> bool:
        """Revoke a token immediately."""
        try:
            token_id = token.split(".")[0]
            if token_id in self.active_tokens:
                del self.active_tokens[token_id]
                return True
        except (KeyError, ValueError, TypeError):
            pass
        return False

    def _create_signature(self, payload: dict[str, Any]) -> str:
        """Create HMAC signature for a payload."""
        payload_str = json.dumps(payload, sort_keys=True)
        return hmac.new(
            self.secret_key.encode(),
            payload_str.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _cleanup_expired_tokens(self) -> None:
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
            logger.info("Cleaned up %d expired tokens", len(expired))


# Global token manager instance
token_manager = None


def init_token_manager(app: Flask) -> UploadTokenManager:
    """Initialize the global token manager with app config."""
    global token_manager  # noqa: PLW0603

    secret_key = app.config.get("SECRET_KEY", secrets.token_hex(32))
    token_lifetime = app.config.get("UPLOAD_TOKEN_LIFETIME", 3600)  # 1 hour default

    token_manager = UploadTokenManager(
        secret_key=secret_key,
        token_lifetime=token_lifetime,
    )

    logger.info(
        "Upload token manager initialized with %ds token lifetime",
        token_lifetime,
    )
    return token_manager


def require_upload_token(
    f: Callable[..., FlaskRouteReturn],
) -> Callable[..., FlaskRouteReturn]:
    """Require a valid upload token for a route.

    The token can be provided in:
    - Query parameter: ?token=xxx
    - Header: X-Upload-Token: xxx
    - Form data: token=xxx
    """

    @wraps(f)
    def decorated_function(
        *args: Any, **kwargs: Any
    ) -> FlaskRouteReturn:  # noqa: ANN401
        # Get token from various sources
        token_from_args = request.args.get("token")
        token_from_headers = request.headers.get("X-Upload-Token")
        token_from_form = request.form.get("token")

        token = token_from_args or token_from_headers or token_from_form

        logger.info("Token validation attempt from %s", request.remote_addr)
        logger.info("Token from args: %s", "Yes" if token_from_args else "No")
        logger.info("Token from headers: %s", "Yes" if token_from_headers else "No")
        logger.info("Token from form: %s", "Yes" if token_from_form else "No")
        logger.info("Final token: %s", "Yes" if token else "No")
        if token:
            logger.info("Token preview: %s...", token[:20])

        if not token:
            logger.warning("No token provided from %s", request.remote_addr)
            return jsonify({"error": "Upload token required"}), 401

        # Get client IP
        client_ip = request.remote_addr

        # Ensure token manager is initialized
        global token_manager  # noqa: PLW0603
        if token_manager is None:
            token_manager = init_token_manager(current_app)

        # Validate token
        is_valid, error = token_manager.validate_token(token, client_ip)

        if not is_valid:
            logger.warning("Invalid token attempt from %s: %s", client_ip, error)
            return jsonify({"error": error or "Invalid token"}), 401

        # Token is valid, proceed with the request
        return f(*args, **kwargs)

    return decorated_function


def generate_upload_url(base_url: str, token: str) -> str:
    """Generate a secure upload URL with embedded token."""
    return f"{base_url}?token={token}"


class RateLimiter:
    """Simple rate limiter for upload endpoints."""

    def __init__(self) -> None:
        """Initialize the rate limiter with default upload limits."""
        self.requests: defaultdict[str, list[datetime]] = defaultdict(list)
        self.upload_limits = {
            "per_minute": 10,
            "per_hour": 100,
            "max_file_size": 16 * 1024 * 1024,  # 16MB
            "max_files_per_request": 10,
        }

    def is_allowed(self, identifier: str) -> tuple[bool, str | None]:
        """Check if a request is allowed based on rate limits."""
        now = datetime.now()  # noqa: DTZ005
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


def rate_limit_upload(
    f: Callable[..., FlaskRouteReturn],
) -> Callable[..., FlaskRouteReturn]:
    """Apply rate limiting to upload endpoints."""

    @wraps(f)
    def decorated_function(
        *args: Any, **kwargs: Any
    ) -> FlaskRouteReturn:  # noqa: ANN401
        # Use token or IP as identifier
        identifier = (
            request.args.get("token")
            or request.headers.get("X-Upload-Token")
            or request.remote_addr
            or "unknown"
        )

        is_allowed, error = rate_limiter.is_allowed(identifier)

        if not is_allowed:
            logger.warning("Rate limit exceeded for %s: %s", identifier, error)
            return jsonify({"error": error}), 429  # Too Many Requests

        return f(*args, **kwargs)

    return decorated_function
