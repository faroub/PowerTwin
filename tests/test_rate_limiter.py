"""Tests for the authentication rate limiter used by the login flow.

The limiter measures one identity per login attempt: every tracked topic is
one username coming from one client identity, so no single user can exhaust
the throttle of every other user and no single client can exhaust the throttle
of every account. An attempt against an unknown username counts the same way
as one against a known one, without revealing which of the two was missing.

The table of active topics is bounded and always expires aged entries, so the
limiter can never grow without limit. The limiter fails, rather than silently
disabling throttling, on an unusable configuration.

"""

import logging
import threading
from typing import Any
from unittest import mock

import pytest

from backend.app.core.limits import MAX_TOPICS, AuthenticationRateLimiter

logger = logging.getLogger(__name__)


def _mock_clock() -> Any:
    """Return a clock that starts its timeline at an arbitrary moment."""
    return mock.MagicMock(return_value=50.0)


def _seconds(clock: Any, value: float) -> float:
    """Return a clock driven forward by ``value`` seconds."""
    clock.return_value += value
    return clock.return_value


@pytest.mark.parametrize(
    ("max_attempts", "lockout_seconds"),
    [
        (0, 60),
        (-1, 60),
        (1, 0),
        (1, -5),
        ("5", 60),
        (5.0, 60),
        (None, 60),
        ("5", None),
        (True, 60),
        (False, 60),
    ],
)
def test_unusable_configuration_fails(
    max_attempts: Any,
    lockout_seconds: Any,
) -> None:
    """A limiter with an unusable configuration refuses to start."""
    with pytest.raises(ValueError):
        AuthenticationRateLimiter(max_attempts=max_attempts, lockout_seconds=lockout_seconds)


def test_valid_configuration_starts() -> None:
    """A documented configuration creates a working limiter."""
    limiter = AuthenticationRateLimiter(max_attempts=5, lockout_seconds=60)
    assert limiter.is_blocked("observer:127.0.0.1") is False
    assert limiter.remaining_attempts("observer:127.0.0.1") == 5


@pytest.mark.parametrize(
    ("username", "client_id", "expected"),
    [
        ("observer", None, "observer:process-local"),
        ("Observer", None, "observer:process-local"),
        (" observer ", " 10.0.0.1 ", "observer:10.0.0.1"),
        ("observer", "10.0.0.1", "observer:10.0.0.1"),
        ("oauth2:admin", None, "oauth2:admin:process-local"),
        ("", None, ":process-local"),
    ],
)
def test_topic_normalizes_username_and_client(
    username: str,
    client_id: str | None,
    expected: str,
) -> None:
    """The topic is the lowercase username and client, never the raw input."""
    assert AuthenticationRateLimiter.topic(username, client_id) == expected


@pytest.mark.asyncio
async def test_unknown_user_counts_the_same_as_known_user() -> None:
    """A login against a name in no row polls the same limiter topic."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)
    topic = limiter.topic("unknown_user_example", "192.168.1.1")

    for _ in range(3):
        limiter.record_attempt(topic)

    assert limiter.is_blocked(topic) is True
    assert limiter.remaining_attempts(topic) == 0


@pytest.mark.asyncio
async def test_unknown_user_does_not_unlock_a_known_user() -> None:
    """Only the failing identity is throttled, never the pair it looses next to."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)
    known = limiter.topic("observer", "192.168.1.1")
    unknown = limiter.topic("unknown_user_example", "192.168.1.1")

    for _ in range(3):
        limiter.record_attempt(known)

    assert limiter.is_blocked(known) is True
    assert limiter.is_blocked(unknown) is False

    for _ in range(3):
        limiter.record_attempt(unknown)

    assert limiter.is_blocked(unknown) is True


@pytest.mark.parametrize(
    ("client_a", "client_b"),
    [
        ("10.0.0.1", "10.0.0.2"),
        ("testclient", "10.0.0.1"),
        (None, "10.0.0.1"),
    ],
)
@pytest.mark.asyncio
async def test_client_rotation_writes_a_new_topic(
    client_a: str | None,
    client_b: str | None,
) -> None:
    """A failing user that changes its client identity keeps its own throttle."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)
    topic_a = limiter.topic("observer", client_a)
    topic_b = limiter.topic("observer", client_b)

    for _ in range(3):
        limiter.record_attempt(topic_a)

    assert limiter.is_blocked(topic_a) is True
    assert limiter.is_blocked(topic_b) is False


@pytest.mark.asyncio
async def test_lockout_expiry_resolves_the_topic() -> None:
    """Attempts older than the window no longer block the identity."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=10)
    clock = _mock_clock()
    limiter._clock = clock
    topic = limiter.topic("observer", "192.168.1.1")

    for _ in range(3):
        limiter.record_attempt(topic)
    assert limiter.is_blocked(topic) is True

    _seconds(clock, 10.0)
    assert limiter.is_blocked(topic) is False
    assert limiter.remaining_attempts(topic) == 3


@pytest.mark.asyncio
async def test_success_resets_the_topic() -> None:
    """A successful login clears the attempts recorded against the identity."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)
    topic = limiter.topic("observer", "192.168.1.1")

    for _ in range(3):
        limiter.record_attempt(topic)

    assert limiter.is_blocked(topic) is True
    limiter.reset(topic)
    assert limiter.is_blocked(topic) is False
    assert limiter.remaining_attempts(topic) == 3


@pytest.mark.asyncio
async def test_cleanup_drops_inactive_topics() -> None:
    """Cleanup removes the windows that no longer carry an active attempt."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=10)
    clock = _mock_clock()
    limiter._clock = clock
    topic = limiter.topic("observer", "192.168.1.1")
    expired = limiter.topic("retired_user", "192.168.1.1")

    # The retired identity failed while the current window was still open.
    for _ in range(3):
        limiter.record_attempt(expired)

    # The live identity fails within the current window.
    _seconds(clock, 20.0)
    for _ in range(3):
        limiter.record_attempt(topic)

    assert limiter.is_blocked(topic) is True

    limiter.cleanup()

    assert limiter.is_blocked(topic) is True
    assert topic in limiter._attempts
    assert limiter.is_blocked(expired) is False
    assert expired not in limiter._attempts


@pytest.mark.asyncio
async def test_cleanup_respects_the_topic_capacity() -> None:
    """Cleanup keeps the table under its capacity by dropping the least used."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)
    clock = _mock_clock()
    limiter._clock = clock
    clock.return_value = 0.0

    for index in range(100):
        limiter.record_attempt(limiter.topic(f"user_{index}", "192.168.1.1"))

    assert len(limiter._attempts) == 100

    _seconds(clock, 60.0)
    limiter.cleanup()

    assert len(limiter._attempts) == 0


@pytest.mark.asyncio
async def test_table_is_bounded_while_active() -> None:
    """Active windows hold their teams, but the table stays under the capacity."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)
    clock = _mock_clock()
    limiter._clock = clock
    clock.return_value = 0.0

    for index in range(200):
        limiter.record_attempt(limiter.topic(f"user_{index}", "192.168.1.1"))

    assert len(limiter._attempts) == 200
    assert len(limiter._attempts) <= MAX_TOPICS


@pytest.mark.asyncio
async def test_reset_all_clears_the_table() -> None:
    """reset_all clears every tracked topic, ready for a fresh run."""
    limiter = AuthenticationRateLimiter(max_attempts=3, lockout_seconds=60)

    limiter.record_attempt(limiter.topic("observer", "192.168.1.1"))
    limiter.record_attempt(limiter.topic("engineer", "192.168.1.1"))

    assert len(limiter._attempts) == 2
    limiter.reset_all()
    assert len(limiter._attempts) == 0
    assert limiter.is_blocked("observer:192.168.1.1") is False


def test_limiter_is_thread_safe() -> None:
    """Record and check can run concurrently without raising."""
    limiter = AuthenticationRateLimiter(max_attempts=5, lockout_seconds=60)
    topic = limiter.topic("observer", "192.168.1.1")

    thread_results = []

    def record_many() -> None:
        try:
            for _ in range(100):
                limiter.record_attempt(topic)
        except Exception as err:  # pragma: no cover - defensive
            thread_results.append(err)

    thread = threading.Thread(target=record_many)
    try:
        thread.start()
        thread.join(timeout=10)
        assert thread_results == []
    finally:
        if thread.is_alive():
            thread.join(timeout=1)

    assert limiter.is_blocked(topic) is True
