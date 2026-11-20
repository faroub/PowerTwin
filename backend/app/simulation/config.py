"""Simulation Engine Configuration Model."""

from typing import Literal
from pydantic import BaseModel, Field, field_validator


class SimulationConfiguration(BaseModel):
    """Configuration parameters for the simulation engine run."""

    tick_step_ns: int = Field(
        default=10_000_000,
        description="Fixed simulation step size in nanoseconds (default: 10ms = 10,000,000 ns = 100 Hz)",
    )
    speed_factor: float = Field(
        default=1.0,
        description="Wall-clock pacing multiplier. 1.0 = 1x real-time, 0.0 = max speed headless.",
    )
    random_seed: int = Field(
        default=42,
        description="Seed for deterministic pseudo-random number generator.",
    )
    error_policy: Literal["FAIL_FAST", "CONTINUE_WITH_FAULT_LOG"] = Field(
        default="FAIL_FAST",
        description="Policy when a task raises an exception: FAIL_FAST aborts, CONTINUE_WITH_FAULT_LOG safe-parks task.",
    )
    max_ticks: int | None = Field(
        default=None,
        description="Optional maximum number of ticks to run before auto-stopping.",
    )

    @field_validator("tick_step_ns")
    @classmethod
    def validate_tick_step(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"tick_step_ns must be strictly positive (> 0), got: {v}")
        return v

    @field_validator("speed_factor")
    @classmethod
    def validate_speed_factor(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(f"speed_factor cannot be negative (< 0.0), got: {v}")
        return v
