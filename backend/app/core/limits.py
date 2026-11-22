"""In-memory authentication rate limiter.

Blocks repeat authentication attempts that exceed the configured threshold per
topic (username + client identity). The limiter is process-local; a cluster of
application instances shares no rate state and must rely on the deployment
port-binding configuration to keep the endpoint unreachable outside the
loopback interface.
"""

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


class AuthenticationRateLimiter:
    """Sliding-window limiter for the authentication endpoints."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 60) -> None:
        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}
        self._lock = Lock()

    def is_blocked(self, topic: str) -> bool:
        """Return True when the topic has exhausted its allowed attempts."""
        with self._lock:
            attempts = self._attempts.get(topic)
            if not attempts:
                return False
            now = time.monotonic()
            window = [t for t in attempts if now - t < self._lockout_seconds]
            return len(window) >= self._max_attempts

    def record_attempt(self, topic: str) -> None:
        """Record a failed authentication attempt against the topic."""
        with self._lock:
            attempts = self._attempts.get(topic)
            if attempts is None:
                attempts = self._attempts[topic] = []
            attempts.append(time.monotonic())

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
            now = time.monotonic()
            window = [t for t in attempts if now - t < self._lockout_seconds]
            return max(0, self._max_attempts - len(window))
