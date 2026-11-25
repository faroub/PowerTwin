"""Traceable Control Command Audit Logger.

Tracks and records setpoint requests, validation decisions, rate limits, interlock checks,
and state transitions with microsecond/nanosecond simulation timestamps.

Every entry is **also** written to the dedicated operator-action journal
(`backend.app.core.operator_journal`), which is the platform's durable,
hash-chained audit trail. This in-memory log is the fast view the control
hierarchy consults; the journal is what survives a restart and what can be
verified afterwards.
"""

import logging
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.app.core.operator_journal import (
    OperatorJournalError,
    get_operator_journal,
)

logger = logging.getLogger(__name__)


class CommandStatus(StrEnum):
    """Status of a control command payload."""

    ACCEPTED = "ACCEPTED"
    REJECTED_INFEASIBLE = "REJECTED_INFEASIBLE"
    REJECTED_INTERLOCK = "REJECTED_INTERLOCK"
    REJECTED_OUT_OF_BOUNDS = "REJECTED_OUT_OF_BOUNDS"
    DERATED = "DERATED"
    FAULT_TRIP = "FAULT_TRIP"


class CommandAuditEntry(BaseModel):
    """Traceable audit record for control actions."""

    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ns: int = Field(description="Simulation tick timestamp in nanoseconds")
    source_layer: str = Field(description="Originating layer e.g. EMS, PPC, OPERATOR")
    target_component: str = Field(description="Target component e.g. PCS_01, BMS_MASTER")
    action_name: str = Field(description="Name of action e.g. DISPATCH_SETPOINT, CLOSE_BREAKER")
    requested_value: dict[str, Any] = Field(default_factory=dict)
    accepted_value: dict[str, Any] = Field(default_factory=dict)
    status: CommandStatus
    reason: str = Field(default="SUCCESS")


class ControlCommandLog:
    """In-memory traceable audit logger for control hierarchy actions."""

    def __init__(self) -> None:
        self._entries: list[CommandAuditEntry] = []

    def log_entry(
        self,
        timestamp_ns: int,
        source_layer: str,
        target_component: str,
        action_name: str,
        requested_value: dict[str, Any],
        accepted_value: dict[str, Any],
        status: CommandStatus,
        reason: str = "SUCCESS",
    ) -> CommandAuditEntry:
        """Create and append a traceable command audit record."""
        entry = CommandAuditEntry(
            timestamp_ns=timestamp_ns,
            source_layer=source_layer,
            target_component=target_component,
            action_name=action_name,
            requested_value=requested_value,
            accepted_value=accepted_value,
            status=status,
            reason=reason,
        )
        self._entries.append(entry)
        self._write_to_journal(entry)
        return entry

    def _write_to_journal(self, entry: CommandAuditEntry) -> None:
        """Write the command to the dedicated operator-action journal.

        A journal that cannot be written is reported as an error and the
        journal marks itself degraded; the error is never swallowed.
        """
        try:
            get_operator_journal().record(
                action=entry.action_name,
                actor=entry.source_layer,
                target=entry.target_component,
                source=entry.source_layer,
                outcome=entry.status.value,
                details={
                    "requested_value": entry.requested_value,
                    "accepted_value": entry.accepted_value,
                    "reason": entry.reason,
                },
                timestamp_ns=entry.timestamp_ns,
            )
        except OperatorJournalError as err:
            logger.error("The command could not reach the journal: %s", err)

    @property
    def entries(self) -> list[CommandAuditEntry]:
        """Return all logged audit entries."""
        return self._entries

    def get_entries_for_target(self, target_component: str) -> list[CommandAuditEntry]:
        """Return audit entries for a specific target component."""
        return [e for e in self._entries if e.target_component == target_component]

    def clear(self) -> None:
        """Clear log entries."""
        self._entries.clear()
