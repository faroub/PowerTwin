"""Configuration Change Audit Logger."""

import datetime

from pydantic import BaseModel, Field

from backend.app.core.secrets import is_sensitive_name, redact_text, redact_value


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
        return record
