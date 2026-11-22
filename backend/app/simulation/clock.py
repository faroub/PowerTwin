"""Deterministic Integer Simulation Clock.

Uses unsigned integer nanoseconds for absolute deterministic time tracking.
Floating-point wall-clock accumulation is strictly prohibited.
"""

from backend.app.simulation.exceptions import InvalidTimeStepError

NANOSECONDS_PER_SECOND: int = 1_000_000_000
DEFAULT_TICK_STEP_NS: int = 10_000_000  # 10 ms = 100 Hz


class SimulationClock:
    """Integer nanosecond simulation clock."""

    def __init__(self, step_ns: int = DEFAULT_TICK_STEP_NS, initial_ticks_ns: int = 0) -> None:
        if step_ns <= 0:
            raise InvalidTimeStepError(f"Tick step must be strictly positive (> 0), got: {step_ns}")
        if initial_ticks_ns < 0:
            raise InvalidTimeStepError(
                f"Initial ticks must be non-negative (>= 0), got: {initial_ticks_ns}"
            )

        self._step_ns: int = step_ns
        self._current_ticks_ns: int = initial_ticks_ns
        self._total_steps: int = 0

    @property
    def step_ns(self) -> int:
        """Return the fixed tick step size in nanoseconds."""
        return self._step_ns

    @property
    def time_ns(self) -> int:
        """Return current simulation time in nanoseconds."""
        return self._current_ticks_ns

    @property
    def time_seconds(self) -> float:
        """Return current simulation time in seconds."""
        return self._current_ticks_ns / NANOSECONDS_PER_SECOND

    @property
    def total_steps(self) -> int:
        """Return total number of steps executed since initialization/reset."""
        return self._total_steps

    @total_steps.setter
    def total_steps(self, total_steps: int) -> None:
        """Restore the total number of steps executed (snapshot resume support).

        Args:
            total_steps: New total step count (must be >= 0).
        """
        if total_steps < 0:
            raise InvalidTimeStepError(
                f"Total steps must be non-negative (>= 0), got: {total_steps}"
            )
        self._total_steps = total_steps

    def restore_total_steps(self, total_steps: int) -> None:
        """Restore the total step counter by a named, public API.

        Args:
            total_steps: New total step count (must be >= 0).
        """
        self.total_steps = total_steps

    def advance(self) -> int:
        """Advance simulation clock by exactly one tick step.

        Returns:
            The new simulation time in nanoseconds.
        """
        self._current_ticks_ns += self._step_ns
        self._total_steps += 1
        return self._current_ticks_ns

    def reset(self, initial_ticks_ns: int = 0, step_ns: int | None = None) -> None:
        """Reset simulation clock to initial state."""
        if initial_ticks_ns < 0:
            raise InvalidTimeStepError(
                f"Initial ticks must be non-negative (>= 0), got: {initial_ticks_ns}"
            )
        if step_ns is not None:
            if step_ns <= 0:
                raise InvalidTimeStepError(
                    f"Tick step must be strictly positive (> 0), got: {step_ns}"
                )
            self._step_ns = step_ns

        self._current_ticks_ns = initial_ticks_ns
        self._total_steps = 0

    def format_timestamp(self) -> str:
        """Return human-readable simulation timestamp string (HH:MM:SS.mmm.uuu)."""
        total_us = self._current_ticks_ns // 1000
        seconds, us = divmod(total_us, 1_000_000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        ms, us = divmod(us, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}.{us:03d}"
