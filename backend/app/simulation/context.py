"""Simulation Context passed to tasks during tick execution."""

from typing import Any

from backend.app.simulation.clock import NANOSECONDS_PER_SECOND, SimulationClock
from backend.app.simulation.event import EventDispatcher, SimulationEvent
from backend.app.simulation.random_manager import SeededRandomManager


class SimulationContext:
    """Execution context providing access to simulation services, clock, and state."""

    def __init__(
        self,
        clock: SimulationClock,
        random: SeededRandomManager,
        events: EventDispatcher,
        run_id: str,
        shared_state: dict[str, Any] | None = None,
    ) -> None:
        self.clock: SimulationClock = clock
        self.random: SeededRandomManager = random
        self.events: EventDispatcher = events
        self.run_id: str = run_id
        self.shared_state: dict[str, Any] = shared_state if shared_state is not None else {}

    @property
    def current_tick_ns(self) -> int:
        """Return current simulation clock timestamp in nanoseconds."""
        return self.clock.time_ns

    @property
    def delta_t_s(self) -> float:
        """Return simulation step size in seconds."""
        return self.clock.step_ns / NANOSECONDS_PER_SECOND

    def emit_event(
        self, name: str, source: str, payload: dict[str, Any] | None = None
    ) -> SimulationEvent:
        """Helper to create and emit a simulation event."""
        event = SimulationEvent(
            name=name,
            timestamp_ns=self.current_tick_ns,
            source=source,
            payload=payload if payload is not None else {},
        )
        self.events.publish(event)
        return event
