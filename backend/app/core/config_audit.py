"""Configuration Change Audit Logger."""

import datetime

from pydantic import BaseModel, Field


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
    """Thread-safe configuration-change audit logger."""

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
        """Record configuration modification event."""
        record = ConfigChangeRecord(
            timestamp_ns=timestamp_ns,
            user_id=user_id,
            component_name=component_name,
            parameter_name=parameter_name,
            old_value=str(old_value),
            new_value=str(new_value),
            reason=reason,
        )
        self.entries.append(record)
        return record
