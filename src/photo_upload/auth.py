"""
Authentication and security for photo upload feature.
"""

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from functools import wraps

from flask import jsonify, request

logger = logging.getLogger(__name__)


class UploadTokenManager:
    """Manages secure tokens for photo upload access.

    This object is shared by every Flask request thread, so all access to
    ``active_tokens`` is serialised by an internal lock.  In particular the
    "have we hit ``max_uses``?" check and the increment that follows it have
    to happen as one atomic step, otherwise concurrent uploads can push a
    token past its cap.

    Memory is bounded by expiring entries on the *validation* path (see
    ``_cleanup_if_due``) rather than only when a new token is minted -- a
    device that stops generating QR codes would otherwise keep every dead
    token forever.

    Expiry is enforced against both the wall clock and a monotonic deadline.
    A Raspberry Pi without a battery-backed clock can have ``time.time()``
    stepped by NTP after boot; a backwards step would otherwise silently
    extend every live token's lifetime.  Whichever deadline fires first
    wins, so the clock can only ever shorten a token's life, never
    lengthen it.
    """

    #: Minimum seconds between full sweeps of the token table.
    CLEANUP_INTERVAL = 300.0

    def __init__(self, secret_key=None, token_lifetime=3600, cleanup_interval=None):
        """
        Initialize the token manager.

        Args:
            secret_key: Secret key for HMAC signatures (will generate if not provided)
            token_lifetime: Token lifetime in seconds (default: 1 hour)
            cleanup_interval: Minimum seconds between full sweeps of the token
                table on the validation path (default: 300)
        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self.token_lifetime = token_lifetime
        self.active_tokens = {}  # Store active tokens with metadata
        self.cleanup_interval = (
            self.CLEANUP_INTERVAL if cleanup_interval is None else cleanup_interval
        )
        # RLock: generate_token/validate_token call the cleanup helpers while
        # already holding the lock.
        self._lock = threading.RLock()
        self._last_cleanup = time.monotonic()

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
        # Wall-clock independent deadline, immune to NTP steps.
        mono_expiry = time.monotonic() + self.token_lifetime

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

        with self._lock:
            # Store token metadata
            self.active_tokens[token_id] = {
                "created": timestamp,
                "expiry": expiry,
                "mono_expiry": mono_expiry,
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

            # Everything below is one atomic step: the use-count check and the
            # increment that follows it must not interleave with another
            # request thread, or the max_uses cap can be overshot.
            with self._lock:
                # Reclaim expired entries on a path that actually runs.  This
                # is throttled to once per cleanup_interval so the common case
                # stays O(1) per request instead of scanning the whole table.
                self._cleanup_if_due()

                # Check if token exists and is not expired
                token_data = self.active_tokens.get(token_id)
                if token_data is None:
                    return False, "Token not found or expired"

                # Check expiry
                if self._is_expired(token_data):
                    self.active_tokens.pop(token_id, None)
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
            with self._lock:
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

    def _is_expired(self, token_data, wall_now=None, mono_now=None):
        """Return True if a token is past either of its deadlines.

        Two clocks are consulted and the *earlier* one wins:

        * ``expiry`` -- wall clock, part of the signed payload and what
          callers are told the expiry is.
        * ``mono_expiry`` -- ``time.monotonic()`` based, unaffected by NTP.

        A backwards wall-clock step (Pi boots with a stale clock, NTP then
        corrects it) would push ``expiry`` far into the future and keep every
        outstanding token alive well past its lifetime; the monotonic
        deadline stops that.  A forwards step expires tokens early, which is
        the safe direction to fail -- the user just rescans the QR code.
        """
        wall_now = time.time() if wall_now is None else wall_now
        if wall_now > token_data["expiry"]:
            return True

        mono_expiry = token_data.get("mono_expiry")
        if mono_expiry is None:
            return False

        mono_now = time.monotonic() if mono_now is None else mono_now
        return mono_now > mono_expiry

    def _cleanup_if_due(self):
        """Run a full sweep, but no more often than ``cleanup_interval``.

        A full sweep is O(number of live tokens), which is bounded by the
        number of QR codes scanned within one token lifetime -- realistically
        a handful on a family device, so a scan is cheap.  Throttling it
        anyway keeps the per-request cost O(1) no matter how the table grows,
        while still guaranteeing dead entries are reclaimed on a code path
        that runs continuously.

        The throttle uses the monotonic clock so a wall-clock jump cannot
        postpone cleanup indefinitely.  Caller must hold the lock.
        """
        if time.monotonic() - self._last_cleanup >= self.cleanup_interval:
            self._cleanup_expired_tokens()

    def _cleanup_expired_tokens(self):
        """Remove expired tokens from memory."""
        with self._lock:
            wall_now = time.time()
            mono_now = time.monotonic()
            expired = [
                token_id
                for token_id, data in self.active_tokens.items()
                if self._is_expired(data, wall_now, mono_now)
            ]
            for token_id in expired:
                del self.active_tokens[token_id]

            self._last_cleanup = mono_now

        if expired:
            # Counts only -- never token material.
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
        # Get token from various sources.
        #
        # SECURITY: the token itself is a bearer credential granting photo
        # upload and delete rights. It must never be written to the log --
        # not in full, and not as a truncated "preview" either. Only the
        # source it arrived on is ever recorded.
        token_from_args = request.args.get("token")
        token_from_headers = request.headers.get("X-Upload-Token")
        token_from_form = request.form.get("token")

        token = token_from_args or token_from_headers or token_from_form

        if token_from_args:
            arrived_via = "query"
        elif token_from_headers:
            arrived_via = "header"
        elif token_from_form:
            arrived_via = "form"
        else:
            arrived_via = "none"

        logger.debug(
            "Upload token presented via %s from %s", arrived_via, request.remote_addr
        )

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
    """Rate limiter for upload endpoints: thread-safe and bounded in memory.

    Three things this has to survive, because the process runs for weeks on a
    Raspberry Pi:

    *Unbounded growth.*  A fresh token is minted for every QR code scan and
    every client IP is tracked too, so the identifier space is effectively
    unbounded over time.  Identifiers whose window has emptied are deleted
    outright (not just pruned to an empty list), both when that identifier is
    seen again and via a periodic sweep that catches the ones that simply
    went quiet.

    *Concurrency.*  Flask serves requests on several threads and the
    prune/count/append sequence is a read-modify-write on shared state, so it
    all runs under a lock.  Without it, a concurrent append can be lost and a
    client slips past its limit.

    *Clock jumps.*  Timestamps come from ``time.monotonic()``, not
    ``datetime.now()``.  A wall clock stepped backwards by NTP (routine on a
    Pi with no battery-backed RTC) would leave recorded times in the future,
    so the hour window would never advance and a throttled client would stay
    throttled until real time caught up.  A forwards step would hand out free
    resets.  The monotonic clock does neither.
    """

    #: Hard cap on how many identifiers are tracked at once.
    MAX_TRACKED_IDENTIFIERS = 10_000
    #: Minimum seconds between opportunistic full sweeps of the table.
    SWEEP_INTERVAL = 60.0
    #: Minimum seconds between the extra sweeps forced when the cap is hit,
    #: so a flood of new identifiers cannot turn every request into a scan.
    CAP_SWEEP_INTERVAL = 1.0

    _MINUTE = 60.0
    _HOUR = 3600.0

    def __init__(self, max_tracked_identifiers=None, sweep_interval=None):
        self.requests = {}
        self.upload_limits = {
            "per_minute": 10,
            "per_hour": 100,
            "max_file_size": 16 * 1024 * 1024,  # 16MB
            "max_files_per_request": 10,
        }
        self.max_tracked_identifiers = (
            self.MAX_TRACKED_IDENTIFIERS
            if max_tracked_identifiers is None
            else max_tracked_identifiers
        )
        self.sweep_interval = (
            self.SWEEP_INTERVAL if sweep_interval is None else sweep_interval
        )
        self._lock = threading.RLock()
        self._last_sweep = time.monotonic()

    def is_allowed(self, identifier):
        """Check if a request is allowed based on rate limits."""
        now = time.monotonic()
        minute_ago = now - self._MINUTE
        hour_ago = now - self._HOUR

        with self._lock:
            self._sweep_if_due(now, self.sweep_interval)

            # Drop timestamps that have aged out of the hour window.
            timestamps = [t for t in self.requests.get(identifier, ()) if t > hour_ago]

            if timestamps:
                self.requests[identifier] = timestamps
            else:
                # Nothing left in the window, so this identifier carries no
                # state worth keeping.  Delete the key instead of leaving an
                # empty list behind, then treat this as a brand new client.
                self.requests.pop(identifier, None)
                if not self._has_room_for_new_identifier(now):
                    return False, "Rate limit exceeded: too many active clients"

            # Count requests in windows
            minute_requests = sum(1 for t in timestamps if t > minute_ago)
            hour_requests = len(timestamps)

            # Check limits
            if minute_requests >= self.upload_limits["per_minute"]:
                return False, "Rate limit exceeded: too many requests per minute"

            if hour_requests >= self.upload_limits["per_hour"]:
                return False, "Rate limit exceeded: too many requests per hour"

            # Record this request
            timestamps.append(now)
            self.requests[identifier] = timestamps

            return True, None

    def _has_room_for_new_identifier(self, now):
        """Whether a not-currently-tracked identifier may be admitted.

        Eviction policy: **nothing already tracked is ever evicted to make
        room.**  Every tracked entry exists precisely because that client has
        requests inside the window, so dropping one hands that client a fresh
        allowance -- and the entries closest to their limit are exactly the
        ones an abuser would want gone.  An LRU or random eviction would let
        a throttled client reset itself just by flooding the table with
        throwaway tokens, which is trivially cheap for it to do.

        So the cap fails closed: expired entries are swept first, and if the
        table is still full the *new* identifier is refused.  The cost is
        that during such a flood a genuinely new client may be turned away
        with a 429 until slots age out, which is self-healing within the hour
        window.  On a device whose real population is a handful of phones,
        reaching 10k live identifiers means something abusive is happening
        anyway, and a temporary 429 beats both exhausting the Pi's memory and
        handing abusers a reset button.

        Caller must hold the lock.
        """
        if len(self.requests) < self.max_tracked_identifiers:
            return True

        self._sweep_if_due(now, self.CAP_SWEEP_INTERVAL)
        return len(self.requests) < self.max_tracked_identifiers

    def _sweep_if_due(self, now, min_interval):
        """Run a full sweep if enough time has passed. Caller holds the lock."""
        if now - self._last_sweep >= min_interval:
            self._sweep(now)

    def _sweep(self, now):
        """Drop every identifier whose window is empty. Caller holds the lock.

        Timestamps are appended in monotonic order, so the last one is the
        newest; if even that has aged out the whole entry is dead.  This is
        the only thing that reclaims identifiers which simply stopped making
        requests -- the per-identifier prune in ``is_allowed`` never runs for
        a client that never comes back.
        """
        hour_ago = now - self._HOUR
        stale = [
            identifier
            for identifier, timestamps in self.requests.items()
            if not timestamps or timestamps[-1] <= hour_ago
        ]
        for identifier in stale:
            del self.requests[identifier]

        self._last_sweep = now


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limit_upload(f):
    """Decorator to apply rate limiting to upload endpoints."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Use token or IP as identifier
        token = request.args.get("token") or request.headers.get("X-Upload-Token")
        identifier = token or request.remote_addr

        is_allowed, error = rate_limiter.is_allowed(identifier)

        if not is_allowed:
            # SECURITY: the identifier is often the upload token itself, which
            # is a bearer credential -- log what it was keyed on, never its
            # value. See require_upload_token for the same rule.
            logger.warning(
                "Rate limit exceeded for client from %s (keyed by %s): %s",
                request.remote_addr,
                "token" if token else "ip",
                error,
            )
            return jsonify({"error": error}), 429  # Too Many Requests

        return f(*args, **kwargs)

    return decorated_function
