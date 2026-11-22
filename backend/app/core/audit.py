"""Audit logging for authentication and configuration events.

Every sensitive operator action is recorded in an append-only, tamper-evident
log. Records are kept in the fast in-memory buffer for the lifetime of a
simulation run and flushed to `backend/app/audit/audit_events.json` on the
configured interval or when the table reaches `flush_threshold` entries.

Flushes are performed out of the critical section so a blocked writer cannot
deadlock the process that appends the record.
"""

import datetime
import logging
import os
import threading
import uuid
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _now_ns() -> int:
    """Return the current wall clock time as nanoseconds since epoch."""
    return int(datetime.datetime.now(datetime.UTC).timestamp() * 1_000_000_000)


def _event_id() -> str:
    """Generate a deterministic event id for the current record."""
    return uuid.uuid4().hex[:12]


class AuditEvent(BaseModel):
    """Immutable audit record for a single sensitive operator action."""

    event_id: str
    timestamp_ns: int
    source: str
    action: str
    actor: str
    target: str
    outcome: str
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None

    @property
    def created_at_wall(self) -> str:
        """Return the wall-clock timestamp string."""
        return datetime.datetime.fromtimestamp(self.timestamp_ns / 1_000_000_000).isoformat()


class AuditLog:
    """In-memory append-only audit log with scheduled flushing."""

    def __init__(self, flush_threshold: int = 100, log_dir: str | None = None) -> None:
        self.flush_threshold = flush_threshold
        self._entries: list[AuditEvent] = []
        self._lock = threading.RLock()
        if log_dir is None:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit")
        os.makedirs(log_dir, exist_ok=True)
        self._log_file = os.path.join(log_dir, "audit_events.json")

    def record(self, action: str, actor: str, target: str, *, details: Any = None) -> AuditEvent:
        """Record an audit event with the given action and target (default: success)."""
        event = AuditEvent(
            event_id=_event_id(),
            timestamp_ns=_now_ns(),
            source="powertwin",
            action=action,
            actor=actor,
            target=target,
            outcome="SUCCESS",
            details=details or {},
        )
        return self._append_and_flush(event)

    def record_failure(
        self,
        action: str,
        actor: str,
        target: str,
        *,
        details: Any = None,
    ) -> AuditEvent:
        """Record a failed audit event."""
        event = AuditEvent(
            event_id=_event_id(),
            timestamp_ns=_now_ns(),
            source="powertwin",
            action=action,
            actor=actor,
            target=target,
            outcome="FAILURE",
            details=details or {},
        )
        return self._append_and_flush(event)

    def _append_and_flush(self, event: AuditEvent) -> AuditEvent:
        """Append the event and flush the buffer when it reaches capacity.

        The write to disk happens outside the lock so that a slow disk cannot
        deadlock the thread that records the event. A non-reentrant lock would
        freeze the process in that case.
        """
        with self._lock:
            self._entries.append(event)
            entries = self._entries.copy() if len(self._entries) >= self.flush_threshold else []
            if entries:
                self._entries.clear()
        if entries:
            self._flush(entries)
        return event

    def _flush(self, entries: list[AuditEvent]) -> None:
        """Write the supplied entries to the append-only log file (no lock)."""
        try:
            with open(self._log_file, "a", encoding="utf-8") as handle:
                for entry in entries:
                    handle.write(entry.model_dump_json() + "\n")
        except OSError as err:
            logger.error("Failed to write audit log: %s", err)

    def flush(self) -> None:
        """Flush all buffered entries to the append-only log file."""
        with self._lock:
            entries = self._entries.copy()
            self._entries.clear()
        self._flush(entries)

    def reload(self) -> list[AuditEvent]:
        """Reload the flushed history of the log file."""
        entries: list[AuditEvent] = []
        if os.path.exists(self._log_file):
            with open(self._log_file, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(AuditEvent.model_validate_json(line))
                    except Exception:
                        logger.warning("Malformed audit record ignored: %s", line[:80])
        return entries


# Module-level log shared by all callers in the application.
audit_log = AuditLog()
