"""Application-scoped simulation runtime and authoritative plant container.

.. admonition:: Simulation-only

    The full platform is constrained to SIMULATION ONLY. This module owns the
    lifecycle of the plant and the simulation engine; no coded path connects to
    physical equipment.

The authoritative plant is attached once during application start-up and is held
in the FastAPI application state. Every API read, every control action and every
snapshot is resolved from that runtime so that:

* the simulation engine never advances on a module-level global,
* the engine runs in a single dedicated thread with wall-clock pacing,
* a plant is owned by the process that created it,
* snapshots capture their own engine state (clock, RNG, tasks and physical
  models).

A module-level fall-back runtime is used when no application handle is
available (unit and scenario tests build their own engine instances: the
app-scoped value is bound by this module on start-up, so both callers resolve
the same instance).

"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from fastapi import Request

from backend.app.simulation.exceptions import SimulationError
from backend.app.simulation.runner import SimulationRunner
from backend.app.simulation.snapshot import SimulationSnapshot

if TYPE_CHECKING:
    from backend.app.simulation.manager import SimulationRunManager
    from backend.app.topology.factory import BuiltPlantInstance

logger = logging.getLogger(__name__)

# Key used by the application to hold the runtime on ``app.state``.
SIMULATION_RUNTIME_KEY = "simulation_runtime"


class SimulationRuntime:
    """App-scoped container for the plant, engine and continuous-run runner.

    The runner is created, but never started, at attachment: the engine ticks
    only when the API, the scenario runner or an explicit start action commands
    it, so the API never blocks indefinitely while a simulation runs.
    """

    def __init__(self) -> None:
        self.active_plant: BuiltPlantInstance | None = None
        self.engine: SimulationRunManager | None = None
        # One runner runs for the lifetime of the attachment unless reset.
        self.runner: SimulationRunner | None = None
        self.fault_engine: Any = None
        self._lock = threading.RLock()

    @property
    def is_attached(self) -> bool:
        """True while the plant, engine and runner are attached and alive."""
        return self.active_plant is not None and self.engine is not None

    def bind_to_app(self, app: Any) -> SimulationRuntime:
        """Bind this runtime as the application-scoped instance.

        Any handle resolved subsequently (request, app instance or the module
        fall-back) returns this same object.
        """
        setattr(app.state, SIMULATION_RUNTIME_KEY, self)
        return self

    def attach_plant(self, plant: BuiltPlantInstance) -> SimulationRuntime:
        """Attach a built plant (engine + runner) to this runtime.

        The runner is instantiated but the engine remains stopped until the API
        starts it. The plant, engine, runner and fault engine stay with the
        runtime for its whole lifetime.
        """
        with self._lock:
            self._stop_runner()

            self.active_plant = plant
            self.engine = plant.simulation_engine
            self.runner = SimulationRunner(self.engine, plant, runtime=self)
            return self

    def drop(self) -> SimulationRuntime:
        """Detach the plant, engine and runner."""
        with self._lock:
            self._stop_runner()
            self.engine = None
            self.active_plant = None
            return self

    def shutdown(self) -> None:
        """Stop the run loop and release every plugin registered on the plant."""
        with self._lock:
            self._stop_runner()
            self.engine = None
            if self.active_plant is not None and hasattr(self.active_plant, "plugin_registry"):
                try:
                    self.active_plant.plugin_registry.shutdown_all()
                except Exception as err:
                    logger.warning("Could not shut down the plugin registry: %s", err)
            self.active_plant = None

    def _stop_runner(self) -> None:
        """Stop the execution thread without touching the plant or engine."""
        if self.runner is not None:
            try:
                self.runner.stop_with_timeout(timeout_s=5.0)
            except Exception as err:
                logger.warning("Could not stop the simulation runner: %s", err)
            self.runner = None
        self.fault_engine = None

    # ------------------------------------------------------------------ #
    # Simulation lifecycle (delegated to the runner when attached).
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Start the continuous, paced execution loop for the active plant."""
        with self._lock:
            runner = self.runner
        if runner is None:
            raise SimulationError("No runner attached; a plant must be attached before start.")
        runner.start()

    def pause(self) -> None:
        """Freeze the execution loop at the current tick boundary."""
        with self._lock:
            runner = self.runner
        if runner is None:
            return
        runner.pause()

    def resume(self) -> None:
        """Resume the execution loop from the paused tick."""
        with self._lock:
            runner = self.runner
        if runner is None:
            return
        runner.resume()

    def stop(self) -> None:
        """Stop the execution loop at the current tick boundary.

        The call returns only once the execution thread has finished, so the
        clock is frozen when the caller observes it: a stop is final, and the
        engine is left in the stopped state rather than in a state a tick that
        was in flight has changed afterwards.
        """
        with self._lock:
            runner = self.runner
        if runner is None:
            return
        runner.stop_with_timeout(timeout_s=5.0)

    def single_step(self) -> list[str]:
        """Execute exactly one simulation tick and return the executed tasks."""
        with self._lock:
            runner = self.runner
        if runner is None:
            raise SimulationError("No runner attached; a plant must be attached before step.")
        return runner.single_step()

    def step(self, num_ticks: int = 1) -> list[str]:
        """Execute num_ticks ticks immediately (non-blocking for the caller).

        The continuous loop is stopped before the batch is executed, so the
        clock advances by exactly ``num_ticks`` ticks and no tick of the loop
        can be counted against the batch. The engine is left in the paused
        state: a step advances the simulation, it does not continue it.
        """
        with self._lock:
            engine = self.engine
        if engine is None:
            raise SimulationError("No engine attached; a plant must be attached before step.")
        # Stop the continuous loop thread before a direct batch so the tick
        # boundary stays deterministic outside of the run loop.
        if self.runner is not None and self.runner.is_running:
            try:
                self.runner.stop_with_timeout(timeout_s=5.0)
            except Exception as err:  # noqa: BLE001
                logger.warning("Could not stop the execution loop: %s", err)
        return engine.step(num_ticks) or []

    def set_speed_factor(self, multiplier: float) -> None:
        """Update simulation wall-clock speed pacing factor."""
        with self._lock:
            runner = self.runner
            engine = self.engine
        if runner is not None:
            runner.set_speed_factor(multiplier)
        if engine is not None:
            engine.set_speed_factor(multiplier)

    def reset(self) -> None:
        """Reset the engine to its initial conditions."""
        with self._lock:
            runner = self.runner
            engine = self.engine
        if runner is not None:
            runner.reset()
        if engine is not None:
            engine.reset()

    def create_snapshot(self) -> SimulationSnapshot:
        """Capture the engine state snapshot for the active plant."""
        with self._lock:
            engine = self.engine
        if engine is None:
            raise SimulationError("No engine attached; a plant must be attached before snapshot.")
        return engine.create_snapshot()

    def restore_snapshot(self, snapshot: SimulationSnapshot) -> None:
        """Restore the engine state snapshot for the active plant."""
        with self._lock:
            engine = self.engine
            runner = self.runner
        if engine is None:
            raise SimulationError("No engine attached; a plant must be attached before restore.")
        engine.restore_snapshot(snapshot)
        if runner is not None and runner.is_running:
            # Snapshots are recorded on a paused engine; resume once restored.
            runner.resume()

    def launch_fault_engine(self, fault_engine: Any) -> None:
        """Attach a fault-injection engine to the runtime snapshot set."""
        with self._lock:
            self.fault_engine = fault_engine

    # ------------------------------------------------------------------ #
    # Status accessors.
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, Any]:
        """Return the active runtime status for the HMI/overview feed."""
        with self._lock:
            runner = self.runner
            engine = self.engine

        if runner is None and engine is None:
            return {
                "status": "NOT_CONNECTED",
                "mode": "SIMULATION_ONLY",
                "current_tick": 0,
                "is_running": False,
                "message": "No active plant simulation instance attached.",
            }

        # A runner without an engine is not a valid runtime state.
        assert engine is not None, "runtime has a runner but no attached engine"

        state_str = engine.state.value if hasattr(engine.state, "value") else str(engine.state)
        return {
            "status": state_str,
            "mode": "SIMULATION_ONLY",
            "current_tick": engine.clock.total_steps,
            "is_running": runner is not None and runner.is_running,
            "message": f"Simulation engine is in state '{state_str}'.",
        }

    def is_running(self) -> bool:
        """True while the execution thread is advancing ticks."""
        with self._lock:
            runner = self.runner
        return runner is not None and runner.is_running


def get_simulation_runtime(
    app: Any = None,
    request: Request | None = None,
) -> SimulationRuntime:
    """Resolve the app-scoped runtime for a request or app handle.

    A *new* runtime is constructed and bound to the first application handle that
    asks for it, so two applications never share a runtime, a plant or an engine.
    The module fall-back instance is returned when no app handle is available
    (unit and scenario tests build their own engine instances). Application
    start-up binds its runtime the same way, so both callers resolve the same
    object.
    """
    base_app = request.app if request is not None else app
    if base_app is not None:
        state = getattr(base_app, "state", None)
        runtime = getattr(state, SIMULATION_RUNTIME_KEY, None)
        if runtime is None:
            runtime = SimulationRuntime()
            setattr(state, SIMULATION_RUNTIME_KEY, runtime)
        return runtime
    return default_runtime


def get_active_simulation_engine(app: Any = None) -> SimulationRunManager | None:
    """Return the active simulation engine (app-scoped)."""
    return get_simulation_runtime(app=app).engine


def get_active_plant(app: Any = None) -> BuiltPlantInstance | None:
    """Return the active plant instance (app-scoped)."""
    return get_simulation_runtime(app=app).active_plant


# Module-level fall-back runtime used when the helpers are called without an
# app handle. Application start-up binds this very instance to the app state so
# that both callers resolve the same object.
default_runtime = SimulationRuntime()
