"""Simulation Snapshot Data Model for Save and Restore."""

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.app.simulation.exceptions import SnapshotIncompatibleError

ENGINE_VERSION: str = "0.1.0"


class SimulationSnapshot(BaseModel):
    """Serializable snapshot payload representing engine state at a specific tick."""

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: str = Field(default=ENGINE_VERSION)
    simulation_run_id: str = Field(description="Simulation run UUID")
    timestamp_ns: int = Field(description="Simulation time in nanoseconds")
    total_steps: int = Field(description="Total steps executed")
    step_ns: int = Field(description="Tick step size in nanoseconds")
    random_state: dict[str, Any] = Field(description="RNG state dictionary")
    shared_state: dict[str, Any] = Field(description="Shared state context dictionary")
    task_states: dict[str, dict[str, Any]] = Field(description="Per-task internal state dictionary")
    created_at_wall: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )

    def validate_compatibility(self, current_version: str = ENGINE_VERSION) -> None:
        """Validate snapshot version compatibility.

        Raises:
            SnapshotIncompatibleError: If snapshot version does not match engine version.
        """
        if self.version != current_version:
            msg = (
                f"Snapshot version '{self.version}' incompatible with "
                f"engine version '{current_version}'"
            )
            raise SnapshotIncompatibleError(msg)
