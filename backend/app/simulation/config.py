"""Simulation Engine Configuration Model."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

#: The speed factor a run uses unless something else is requested: 1.0 is
#: real time.
DEFAULT_SPEED_FACTOR = 1.0

#: The smallest wall-clock speed factor the platform accepts.
#:
#: 0.0 is not a missing value: it is the documented "run as fast as the host
#: allows" setting, so it is a valid request and not one to be refused.
MIN_SPEED_FACTOR = 0.0

#: The largest wall-clock speed factor the platform accepts (100x real time).
#:
#: The bound is the one the engine specification documents. A factor without
#: an upper limit is a command the platform cannot execute meaningfully: the
#: pacing target becomes shorter than the time it takes to execute a tick,
#: which turns the simulation into an unbounded CPU load while the operator
#: believes the clock is being paced.
MAX_SPEED_FACTOR = 100.0


def validate_speed_factor(value: float) -> float:
    """Return the speed factor if it is inside the permitted range.

    The same bound is applied at every boundary that accepts a speed factor:
    the configuration model, the engine, the runner and the control endpoint.
    A limit that exists at one boundary only is a limit a caller can walk
    around.
    """
    if value < MIN_SPEED_FACTOR or value > MAX_SPEED_FACTOR:
        raise ValueError(
            f"speed_factor must be between {MIN_SPEED_FACTOR} and {MAX_SPEED_FACTOR}, got: {value}"
        )
    return value


class SimulationConfiguration(BaseModel):
    """Configuration parameters for the simulation engine run."""

    tick_step_ns: int = Field(
        default=10_000_000,
        description="Fixed step in nanoseconds (default: 10ms = 10,000,000 ns = 100 Hz)",
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
        description="Policy when task raises exception: FAIL_FAST or CONTINUE_WITH_FAULT_LOG.",
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
    def check_speed_factor(cls, v: float) -> float:
        # The shared function decides the range; the method only routes the
        # field through it, so the model cannot drift from the other
        # boundaries.
        return validate_speed_factor(v)
