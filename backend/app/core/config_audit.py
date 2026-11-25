"""Configuration Change Audit Logger.

Every configuration change is recorded here and written to the dedicated
operator-action journal (`backend.app.core.operator_journal`), which is the
platform's durable, hash-chained audit trail.
"""

import datetime
import logging

from pydantic import BaseModel, Field

from backend.app.core.operator_journal import (
    OperatorJournalError,
    get_operator_journal,
)
from backend.app.core.secrets import is_sensitive_name, redact_text, redact_value

logger = logging.getLogger(__name__)


class ConfigChangeRecord(BaseModel):
    """Immutable audit record for configuration changes."""

    timestamp_ns: int
    user_id: str
    component_name: str
    parameter_name: str
    old_value: str
    new_value: str
    reason: str
    created_at_wall: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )


class ConfigChangeAuditLog:
    """Thread-safe configuration-change audit logger.

    Values of sensitive parameters (passwords, tokens, keys, ...) are redacted
    before the record is stored, so an audit trail can never become a
    secondary store of credentials.
    """

    def __init__(self) -> None:
        self.entries: list[ConfigChangeRecord] = []

    def log_change(
        self,
        timestamp_ns: int,
        user_id: str,
        component_name: str,
        parameter_name: str,
        old_value: str,
        new_value: str,
        reason: str = "CONFIGURATION_UPDATED",
    ) -> ConfigChangeRecord:
        """Record configuration modification event.

        A sensitive parameter name causes both the old and the new value to be
        replaced by a redaction placeholder.
        """
        if is_sensitive_name(parameter_name):
            stored_old = str(redact_value(old_value))
            stored_new = str(redact_value(new_value))
        else:
            stored_old = redact_text(str(old_value))
            stored_new = redact_text(str(new_value))

        record = ConfigChangeRecord(
            timestamp_ns=timestamp_ns,
            user_id=user_id,
            component_name=component_name,
            parameter_name=parameter_name,
            old_value=stored_old,
            new_value=stored_new,
            reason=reason,
        )
        self.entries.append(record)
        self._write_to_journal(record)
        return record

    def _write_to_journal(self, record: ConfigChangeRecord) -> None:
        """Write the change to the dedicated operator-action journal.

        A journal that cannot be written is reported as an error and the
        journal marks itself degraded; the error is never swallowed.
        """
        try:
            get_operator_journal().record(
                action="CONFIGURATION_CHANGE",
                actor=record.user_id,
                target=f"{record.component_name}.{record.parameter_name}",
                source="CONFIG",
                outcome="SUCCESS",
                details={
                    "old_value": record.old_value,
                    "new_value": record.new_value,
                    "reason": record.reason,
                },
                timestamp_ns=record.timestamp_ns,
            )
        except OperatorJournalError as err:
            logger.error("The configuration change could not reach the journal: %s", err)
