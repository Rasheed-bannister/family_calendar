"""Tests for src/photo_upload/auth.py."""

import logging
import sys
import threading
import time

import pytest
from flask import Flask, jsonify

from src.photo_upload import auth as auth_module
from src.photo_upload.auth import (
    RateLimiter,
    UploadTokenManager,
    generate_upload_url,
    rate_limit_upload,
    require_upload_token,
)


@pytest.fixture
def token_manager():
    """Create a token manager with a known secret."""
    return UploadTokenManager(secret_key="test-secret-key", token_lifetime=3600)


@pytest.fixture
def protected_app(token_manager):
    """A minimal Flask app with a single token-protected route."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/protected", methods=["GET", "POST"])
    @require_upload_token
    def protected():
        return jsonify({"ok": True})

    previous = auth_module.token_manager
    auth_module.token_manager = token_manager
    yield app
    auth_module.token_manager = previous


@pytest.fixture
def rate_limited_app():
    """A minimal Flask app with a single rate-limited route."""
    app = Flask(__name__)
    app.config["TESTING"] = True

    @app.route("/limited")
    @rate_limit_upload
    def limited():
        return jsonify({"ok": True})

    previous = auth_module.rate_limiter
    auth_module.rate_limiter = RateLimiter()
    yield app
    auth_module.rate_limiter = previous


def _run_concurrently(worker, thread_count):
    """Run ``worker`` on real threads all released together by a barrier.

    The interpreter switch interval is shrunk for the duration so that a lost
    update in unsynchronised code shows up every run rather than occasionally.
    """
    barrier = threading.Barrier(thread_count)
    results = []
    results_lock = threading.Lock()

    def runner():
        barrier.wait()
        outcome = worker()
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=runner) for _ in range(thread_count)]
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        sys.setswitchinterval(previous_interval)

    assert all(not thread.is_alive() for thread in threads), "worker thread hung"
    return results


def _concurrent_allow_round(limiter, identifier, thread_count):
    """One barrier-synchronised burst of is_allowed calls."""
    return _run_concurrently(lambda: limiter.is_allowed(identifier)[0], thread_count)


def _concurrent_validate_round(manager, token, thread_count):
    """One barrier-synchronised burst of validate_token calls."""
    return _run_concurrently(lambda: manager.validate_token(token)[0], thread_count)


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


def _logged_messages(caplog):
    """Return every captured log message as rendered text."""
    return [record.getMessage() for record in caplog.records]


def _assert_token_absent(caplog, token):
    """Fail if the token, its id half or a prefix of it was logged."""
    messages = _logged_messages(caplog)
    joined = "\n".join(messages)

    assert token not in joined, "full token written to the log"
    token_id = token.split(".")[0]
    assert token_id not in joined, "token id written to the log"
    assert token[:20] not in joined, "token preview written to the log"


class TestTokenNeverLogged:
    """The bearer token must never reach the log, at any level."""

    def test_token_from_query_not_logged(self, protected_app, token_manager, caplog):
        token = token_manager.generate_token()["token"]
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            response = client.get(f"/protected?token={token}")

        assert response.status_code == 200
        _assert_token_absent(caplog, token)

    def test_token_from_header_not_logged(self, protected_app, token_manager, caplog):
        token = token_manager.generate_token()["token"]
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            response = client.get("/protected", headers={"X-Upload-Token": token})

        assert response.status_code == 200
        _assert_token_absent(caplog, token)

    def test_token_from_form_not_logged(self, protected_app, token_manager, caplog):
        token = token_manager.generate_token()["token"]
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            response = client.post("/protected", data={"token": token})

        assert response.status_code == 200
        _assert_token_absent(caplog, token)

    def test_rejected_token_not_logged(self, protected_app, caplog):
        bogus = "bogus-token-id.bogus-signature"  # pragma: allowlist secret
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            response = client.get(f"/protected?token={bogus}")

        assert response.status_code == 401
        joined = "\n".join(_logged_messages(caplog))
        assert bogus not in joined
        assert "bogus-token-id" not in joined

    def test_source_is_still_recorded_for_debugging(
        self, protected_app, token_manager, caplog
    ):
        """Useful context survives the cleanup, just without the credential."""
        token = token_manager.generate_token()["token"]
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            client.get("/protected", headers={"X-Upload-Token": token})

        joined = "\n".join(_logged_messages(caplog))
        assert "header" in joined

    def test_missing_token_logs_warning_and_401(self, protected_app, caplog):
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            response = client.get("/protected")

        assert response.status_code == 401
        assert any(record.levelno >= logging.WARNING for record in caplog.records)

    def test_logging_is_not_chatty(self, protected_app, token_manager, caplog):
        """A successful auth should not emit a burst of INFO lines per request."""
        token = token_manager.generate_token()["token"]
        caplog.set_level(logging.DEBUG)

        with protected_app.test_client() as client:
            client.get(f"/protected?token={token}")

        auth_records = [
            record
            for record in caplog.records
            if record.name == "src.photo_upload.auth"
        ]
        assert len(auth_records) <= 1
        assert all(record.levelno <= logging.DEBUG for record in auth_records)


#: How long ago a "the sweep is overdue" marker should claim the last sweep was.
_LONG_AGO = 10_000


class TestRateLimiterMemoryBounds:
    """The limiter must not accumulate identifiers for weeks of uptime."""

    def test_identifier_with_empty_window_is_dropped(self):
        """An emptied window must delete the key, not leave an empty list."""
        limiter = RateLimiter()
        limiter.is_allowed("quiet-client")

        # This is exactly the state an expired window leaves behind.
        limiter.requests["quiet-client"] = []
        limiter._last_sweep = time.monotonic() - _LONG_AGO

        # Some other client makes a request; the quiet one never returns.
        limiter.is_allowed("other-client")

        assert "quiet-client" not in limiter.requests

    def test_identifier_whose_requests_aged_out_is_dropped(self):
        """A client that went quiet an hour ago must be reclaimed."""
        limiter = RateLimiter()
        limiter.is_allowed("quiet-client")

        # Push its only request outside the one hour window.
        limiter.requests["quiet-client"] = [time.monotonic() - 2 * 3600]
        limiter._last_sweep = time.monotonic() - _LONG_AGO

        limiter.is_allowed("other-client")

        assert "quiet-client" not in limiter.requests
        assert "other-client" in limiter.requests

    def test_active_identifier_survives_a_sweep(self):
        """Guard: sweeping must not throw away clients still in their window."""
        limiter = RateLimiter()
        limiter.is_allowed("busy-client")
        limiter._last_sweep = time.monotonic() - _LONG_AGO

        limiter.is_allowed("other-client")

        assert "busy-client" in limiter.requests
        assert len(limiter.requests["busy-client"]) == 1

    def test_tracked_identifier_cap_holds(self):
        """A flood of distinct identifiers cannot grow the table without end."""
        limiter = RateLimiter()

        for index in range(10_050):
            limiter.is_allowed(f"client-{index}")

        assert len(limiter.requests) <= 10_000
        assert limiter.max_tracked_identifiers == 10_000

    def test_cap_refuses_new_identifiers_instead_of_evicting_tracked_ones(self):
        """Guard: the eviction policy must never reset a throttled client.

        Evicting an existing entry to make room would let an abuser clear its
        own rate-limit state simply by flooding the table with throwaway
        tokens, so the cap fails closed on the new identifier instead.
        """
        limiter = RateLimiter(max_tracked_identifiers=2)

        for _ in range(limiter.upload_limits["per_minute"]):
            allowed, _ = limiter.is_allowed("throttled")
            assert allowed is True

        blocked, error = limiter.is_allowed("throttled")
        assert blocked is False
        assert "minute" in error.lower()

        limiter.is_allowed("second-client")

        # The table is now full. Flood it with fresh identifiers.
        for index in range(50):
            allowed, error = limiter.is_allowed(f"flood-{index}")
            assert allowed is False
            assert "active clients" in error.lower()

        assert len(limiter.requests) == 2
        assert "throttled" in limiter.requests

        # The throttled client is still throttled -- it got no free reset.
        still_blocked, _ = limiter.is_allowed("throttled")
        assert still_blocked is False


class TestRateLimiterConcurrency:
    """Concurrent callers must not be able to slip past the limit."""

    def test_concurrent_requests_do_not_exceed_limit(self):
        identifier = "shared-client"
        thread_count = 60

        # Repeated because a lost update is a race: several rounds make an
        # unsynchronised implementation fail essentially every run.
        for _round in range(8):
            limiter = RateLimiter()
            limit = limiter.upload_limits["per_minute"]

            results = _concurrent_allow_round(limiter, identifier, thread_count)

            assert len(results) == thread_count
            allowed = sum(1 for outcome in results if outcome)
            assert allowed <= limit
            # Every granted request must also have been recorded; a lost
            # append is what lets the next caller through when it should not.
            assert len(limiter.requests[identifier]) == allowed


class TestRateLimiterClock:
    """The limiter must not be steerable by wall-clock jumps."""

    def test_window_uses_the_monotonic_clock(self):
        """Recorded times come from time.monotonic(), which NTP cannot step.

        A wall clock stepped backwards leaves recorded times in the future, so
        the hour window stops advancing and a throttled client stays throttled;
        stepped forwards it hands out free resets.
        """
        limiter = RateLimiter()

        before = time.monotonic()
        limiter.is_allowed("clock-client")
        after = time.monotonic()

        (recorded,) = limiter.requests["clock-client"]
        assert isinstance(recorded, float)
        assert before <= recorded <= after


class TestTokenManagerConcurrency:
    """max_uses must hold when many threads validate the same token."""

    def test_concurrent_validation_does_not_exceed_max_uses(self, token_manager):
        max_uses = 5
        thread_count = 60

        # Repeated for the same reason as the rate limiter burst above.
        for _round in range(8):
            token = token_manager.generate_token()["token"]
            token_id = token.split(".")[0]
            token_manager.active_tokens[token_id]["max_uses"] = max_uses

            results = _concurrent_validate_round(token_manager, token, thread_count)

            accepted = sum(1 for outcome in results if outcome)
            assert accepted <= max_uses
            assert token_manager.active_tokens[token_id]["uses"] <= max_uses


class TestTokenCleanupOnValidation:
    """Dead tokens must be reclaimed without waiting for a new one to be minted."""

    def test_expired_tokens_reclaimed_on_validate(self, token_manager):
        live = token_manager.generate_token()["token"]
        dead_id = token_manager.generate_token()["token"].split(".")[0]
        token_manager.active_tokens[dead_id]["expiry"] = time.time() - 100

        # The sweep is overdue and no new token will be generated.
        token_manager._last_cleanup = time.monotonic() - _LONG_AGO

        is_valid, error = token_manager.validate_token(live)

        assert is_valid is True
        assert error is None
        assert dead_id not in token_manager.active_tokens

    def test_sweep_is_throttled_between_intervals(self):
        """Guard: validation stays O(1); it does not rescan on every request."""
        manager = UploadTokenManager(
            secret_key="test-secret-key", token_lifetime=3600, cleanup_interval=3600
        )
        live = manager.generate_token()["token"]
        dead_id = manager.generate_token()["token"].split(".")[0]
        manager.active_tokens[dead_id]["expiry"] = time.time() - 100

        manager.validate_token(live)

        assert dead_id in manager.active_tokens

    def test_zero_interval_sweeps_on_every_validation(self):
        """Guard: the throttle is configurable down to "always"."""
        manager = UploadTokenManager(
            secret_key="test-secret-key", token_lifetime=3600, cleanup_interval=0
        )
        live = manager.generate_token()["token"]
        dead_id = manager.generate_token()["token"].split(".")[0]
        manager.active_tokens[dead_id]["expiry"] = time.time() - 100

        manager.validate_token(live)

        assert dead_id not in manager.active_tokens


class TestTokenClockJumps:
    """A wall-clock jump must never lengthen a token's life."""

    def test_backward_wall_clock_jump_does_not_extend_a_token(
        self, token_manager, monkeypatch
    ):
        """A Pi with no battery-backed RTC boots with a stale, fast clock.

        The token is therefore signed with a wall-clock expiry a year out.
        NTP then steps the clock back to the truth, at which point the stored
        expiry alone would keep the token alive for a year.
        """
        a_year = 365 * 24 * 3600
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + a_year)
        result = token_manager.generate_token()
        monkeypatch.undo()  # NTP corrects the clock backwards

        token_id = result["token"].split(".")[0]
        # The signature still matches: nothing about the token was tampered
        # with, the clock moved underneath it.
        assert (
            token_manager.active_tokens[token_id]["expiry"] > time.time() + a_year / 2
        )

        # An hour of uptime has now passed, so the token's real lifetime is
        # over. Simulated on the monotonic deadline rather than by sleeping.
        token_manager.active_tokens[token_id]["mono_expiry"] = time.monotonic() - 1

        is_valid, error = token_manager.validate_token(result["token"])

        assert is_valid is False
        assert "expired" in error.lower()
        assert token_id not in token_manager.active_tokens

    def test_healthy_token_is_unaffected(self, token_manager):
        """Guard: the extra deadline must not expire ordinary tokens."""
        result = token_manager.generate_token()

        is_valid, error = token_manager.validate_token(result["token"])

        assert is_valid is True
        assert error is None


class TestRateLimitLoggingNeverLeaksToken:
    """The rate limiter keys on the bearer token; it must not log it."""

    def test_rate_limit_warning_omits_the_token(self, rate_limited_app, caplog):
        token = "rl-token-id.rl-signature"  # pragma: allowlist secret
        caplog.set_level(logging.DEBUG)

        limit = auth_module.rate_limiter.upload_limits["per_minute"]
        with rate_limited_app.test_client() as client:
            for _ in range(limit):
                assert client.get(f"/limited?token={token}").status_code == 200
            response = client.get(f"/limited?token={token}")

        assert response.status_code == 429

        joined = "\n".join(_logged_messages(caplog))
        assert "Rate limit exceeded" in joined
        assert token not in joined, "full token written to the log"
        assert "rl-token-id" not in joined, "token id written to the log"
