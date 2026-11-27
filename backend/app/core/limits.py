"""In-memory authentication rate limiter.

The limiter throttles repeat authentication attempts per **identity**: every
tracked topic is one username coming from one client identity, so a single
user that repeatedly fails credentials can never exhaust the throttle of
every other user on the deployment. Uniquing by identity alone would expose
the deployment to every possible username; uniquing by user alone would
expose the deployment to every possible client. The combination protects
both.

Once the identity is part of the key, an attempt against an unknown username
is counted just like an attempt against a known one, without revealing which
of the two was missing: the gate has to name the failure and nothing else.

The table of active topics is bounded and always expires aged entries, so
the limiter can never grow without limit: every window that carries no active
attempt is dropped, and the least recently used topics are evicted when the
table passes its capacity bound.

The limiter fails, rather than silently disabling throttling, on an unusable
configuration: an attempted `max_attempts` or lockout window of zero either
opens the gate to every login attempt or locks the gate on every login
attempt, and non-integers cannot carry a deterministic threshold.

The limiter is process-local; a cluster of application instances shares no
rate state and must rely on the deployment port-binding configuration to keep
the endpoint unreachable outside the loopback interface.
"""

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock

logger = logging.getLogger(__name__)

#: The maximum number of distinct identities that the limiter tracks. The
#: least recently used identities are evicted first, so the table never
#: grows beyond this bound. A value of one hundred thousand holds a
#: deployment-sized campaign of login attempts without risk.
MAX_TOPICS: int = 100_000


class AuthenticationRateLimiter:
    """Sliding-window limiter for one authentication identity."""

    def __init__(
        self,
        max_attempts: int = 5,
        lockout_seconds: int = 60,
        clock: Callable[[], float] | None = None,
    ) -> None:
        for value, name in (
            (max_attempts, "max_attempts"),
            (lockout_seconds, "lockout_seconds"),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer, got {value!r}")
            if value < 1:
                raise ValueError(
                    f"SECURITY VIOLATION: {name} must be at least 1: a value of 0 "
                    "blocks every login attempt for every user of the deployment"
                )

        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        self._attempts: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = Lock()
        self._clock = clock if clock is not None else time.monotonic

    @staticmethod
    def topic(username: str, client_id: str | None) -> str:
        """Build the identification key that carries one login attempt.

        The key combines the username with the client identity so that one
        failing user can never exhaust the throttle of every other user and
        one trying client can never exhaust the throttle of every account.

        Unknown usernames keep the same shape as known ones, so the attempt
        counts consistently and the failure never names the difference
        between them.

        Returns:
            A string that identifies one user attempting from one identity.
        """
        username_ = str(username).strip().lower()
        client_ = str(client_id).strip().lower() if client_id is not None else "process-local"
        return f"{username_}:{client_}"

    def is_blocked(self, topic: str) -> bool:
        """Return True when the topic has exhausted its allowed attempts."""
        with self._lock:
            attempts = self._attempts.get(topic)
            if not attempts:
                return False
            now = self._clock()
            window = [t for t in attempts if now - t < self._lockout_seconds]
            self._attempts[topic] = window
            self._attempts.move_to_end(topic)
            return len(window) >= self._max_attempts

    def record_attempt(self, topic: str) -> None:
        """Record a failed authentication attempt against the topic."""
        with self._lock:
            attempts = self._attempts[topic] = self._attempts.get(topic, [])
            attempts.append(self._clock())
            self._attempts.move_to_end(topic)
            self._evict()

    def reset(self, topic: str) -> None:
        """Clear recorded attempts for the topic."""
        with self._lock:
            self._attempts.pop(topic, None)

    def reset_all(self) -> None:
        """Clear the whole limiter table (used by tests and shutdown)."""
        with self._lock:
            self._attempts.clear()

    def remaining_attempts(self, topic: str) -> int:
        """Return the number of attempts still allowed for the topic."""
        with self._lock:
            attempts = self._attempts.get(topic)
            if not attempts:
                return self._max_attempts
            now = self._clock()
            window = [t for t in attempts if now - t < self._lockout_seconds]
            return max(0, self._max_attempts - len(window))

    def cleanup(self) -> None:
        """Expire the tables of inactive topics and trim the table to its bound.

        Called on shutdown or by operator tooling to keep the table small:
        every window without an active attempt is dropped and the least
        recently used topics are evicted when the table passes its capacity.
        """
        with self._lock:
            self._evict()

    def _evict(self) -> None:
        """Prune the table of aged entries and drop it to the capacity bound."""
        now = self._clock()
        # Drop every topic whose lockout window carries no attempt at all.
        expired = [
            topic
            for topic, attempts in self._attempts.items()
            if not any(t > now - self._lockout_seconds for t in attempts)
        ]
        for topic in expired:
            del self._attempts[topic]
        # Cap the table at the size bound, dropping the least used topics first.
        while len(self._attempts) > MAX_TOPICS:
            self._attempts.popitem(last=False)
