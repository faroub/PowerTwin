"""Simulation Runner — authoritative, thread-safe execution loop.

.. admonition:: Simulation-only

    This module is part of the lifecycle-secure simulation-only platform, see
    ``docs/04_SIMULATION_ENGINE_SPECIFICATION.md``.

An active simulation needs more than a state machine: ``start()`` must begin a
continuous, paced tick loop, and the API must be able to control the loop
without ever blocking the FastAPI event loop.

Execution order is owned by ``SimulationRunManager`` (scheduler + clock), this
runner owns the *thread* and the *control* surface:

    * deterministic wall-clock pacing around the fixed ``tick_step_ns``
    * isolated reset, start, pause, resume, single-step, and shutdown paths
    * clean teardown on application shutdown

The runner keeps a weak reference to the engine: every lifecycle call and every
loop iteration resolves the executing engine from the application-scoped
runtime so an overridden engine (tests, secondary engines) is adopted without
leaking plant or clock state.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from backend.app.simulation.config import validate_speed_factor
from backend.app.simulation.exceptions import SimulationError
from backend.app.simulation.manager import SimulationRunManager
from backend.app.simulation.state import SimulationState

if TYPE_CHECKING:
    from backend.app.simulation.runtime import SimulationRuntime

logger = logging.getLogger(__name__)


class SimulationRunner:
    """API-facing simulation runner backed by a dedicated execution thread.

    * ``start()`` begins the continuous execution loop,
    * ``pause()``/``resume()`` freeze and unfreeze the loop at tick boundaries,
    * ``stop()``/``shutdown()`` tear the thread down cleanly,
    * ``single_step()``/``step()`` execute ticks outside of the loop thread,
    * the loop never blocks the caller and never busy-waits without an engine.
    """

    def __init__(
        self,
        manager: SimulationRunManager,
        plant: Any = None,
        runtime: SimulationRuntime | None = None,
    ) -> None:
        self._manager: SimulationRunManager = manager
        self._plant: Any = plant
        # The runtime owns the authoritative engine; every iteration resolves it.
        self._runtime: SimulationRuntime | None = runtime

        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._paused: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._action_lock = threading.Lock()
        # The generation of the thread that currently owns the runner. Every
        # start increments it; a thread that finds a newer generation has
        # been superseded and must neither tick nor clear the runner state.
        self._generation: int = 0

        self._error: Exception | None = None
        self._started_at_wall: float = 0.0
        self._speed_factor: float = 1.0

    # ---------------------------------------------------------------- #
    # Public lifecycle
    # ---------------------------------------------------------------- #

    @property
    def manager(self) -> SimulationRunManager | None:
        """Underlying simulation engine instance."""
        return self._resolve_manager()

    @property
    def plant(self) -> Any:
        """Underlying built plant instance."""
        return self._plant

    @property
    def is_running(self) -> bool:
        """True while the execution thread is actively driving ticks."""
        return self._running

    @property
    def speed_factor(self) -> float:
        return self._speed_factor

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _resolve_manager(self) -> SimulationRunManager | None:
        """Resolve the authoritative engine; prefer an overridden runtime engine."""
        if self._runtime is not None:
            # The runtime owns the authoritative engine; follow the override.
            engine = self._runtime.engine
            if engine is not None:
                return engine
        return self._manager

    def start(self) -> None:
        """Start or resume the continuous execution loop.

        Every start begins a new **generation**. The thread of the previous
        generation is on its way out when the next start arrives, and it must
        not be adopted: a thread that is about to exit would stop ticking as
        soon as it noticed the new generation, and it would clear the state
        of the generation that replaced it. The generation counter lets every
        thread recognise that it has been superseded, and lets only the
        current generation clear the runner state.
        """
        with self._action_lock:
            if self._running and not self._paused:
                logger.warning("Simulation runner is already running.")
                return

            self._running = True
            self._paused = False
            self._stop_event.clear()

            self._generation += 1
            generation = self._generation
            thread = threading.Thread(
                target=self._execution_loop,
                args=(generation,),
                name="PowerTwin-simulation-run",
                daemon=True,
            )
            self._thread = thread

        manager = self._resolve_manager()
        if manager is not None:
            manager.start()
        self._started_at_wall = time.perf_counter()

        thread.start()

    def pause(self) -> None:
        """Pause the execution loop at the next tick boundary."""
        with self._action_lock:
            self._paused = True
        manager = self._resolve_manager()
        if manager is not None:
            manager.pause()

    def resume(self) -> None:
        """Resume a paused execution loop."""
        with self._action_lock:
            self._paused = False
        manager = self._resolve_manager()
        if manager is not None:
            manager.resume()

    def stop(self) -> None:
        """Stop the execution loop and mark the engine as stopped."""
        with self._action_lock:
            self._running = False
            self._paused = False
            self._stop_event.set()
        manager = self._resolve_manager()
        if manager is not None:
            manager.stop()

    def stop_with_timeout(self, timeout_s: float = 10.0) -> bool:
        """Stop the runner and wait for the thread to finish cleanly.

        The thread that is stopped is captured before the stop is issued: the
        loop clears ``self._thread`` in its finally block, so the liveness
        check must not read the instance attribute after the join, and a
        generation that was started in the meantime must not be joined
        instead of the one that was stopped.
        """
        thread = self._thread
        self.stop()
        if thread is not None:
            thread.join(timeout=timeout_s)
            return not thread.is_alive()
        return True

    def shutdown(self) -> None:
        """Graceful teardown: stop the loop, reset the engine, clean up resources."""
        self.stop_with_timeout()
        try:
            manager = self._resolve_manager()
            if manager is not None:
                manager.reset()
        except Exception as err:
            logger.error("Error resetting simulation engine on shutdown: %s", err)

    def single_step(self) -> list[str]:
        """Execute exactly one tick outside of the loop thread."""
        return self._execute_steps(1)

    def step(self, num_ticks: int = 1) -> list[str]:
        """Execute num_ticks ticks outside of the loop thread."""
        return self._execute_steps(num_ticks)

    def _execute_steps(self, num_ticks: int) -> list[str]:
        """Execute a tick batch directly on the authoritative resolver manager."""
        manager = self._resolve_manager()
        if manager is None:
            raise SimulationError("No simulation engine attached to this runner")
        return manager.step(num_ticks)

    def run_headless(self, max_ticks: int) -> int:
        """Run max_ticks at maximum speed (no wall-clock pacing)."""
        manager = self._resolve_manager()
        if manager is None:
            raise SimulationError("No simulation engine attached to this runner")
        return manager.run_headless(max_ticks)

    def set_speed_factor(self, multiplier: float) -> None:
        """Update simulation wall-clock speed pacing factor.

        The multiplier is checked against the same range the configuration
        model and the control endpoint use, so a factor that is refused at
        the API cannot reach the runner by another route.
        """
        self._speed_factor = validate_speed_factor(multiplier)
        manager = self._resolve_manager()
        if manager is not None:
            manager.set_speed_factor(multiplier)

    def reset(self) -> None:
        """Reset the engine to its initial conditions."""
        self.stop()
        manager = self._resolve_manager()
        if manager is not None:
            manager.reset()

    def create_snapshot(self) -> Any:
        """Capture engine state snapshot."""
        manager = self._resolve_manager()
        if manager is None:
            raise SimulationError("No simulation engine attached to this runner")
        return manager.create_snapshot()

    def restore_snapshot(self, snapshot: Any) -> None:
        """Restore engine state from a snapshot."""
        manager = self._resolve_manager()
        if manager is None:
            raise SimulationError("No simulation engine attached to this runner")
        manager.restore_snapshot(snapshot)

    # ---------------------------------------------------------------- #
    # Execution loop
    # ---------------------------------------------------------------- #

    def _execution_loop(self, generation: int) -> None:
        """Loop thread: advance the engine at the configured simulation rate.

        Every iteration resolves the engine from the application-scoped runtime
        so an overridden engine is adopted without leaking plant state.

        Args:
            generation: The generation this thread was started for. The thread
                stops as soon as a newer generation has taken over, and it
                only clears the runner state while it is still the current
                generation.
        """
        try:
            last_pace_wall = time.perf_counter()
            while True:
                with self._action_lock:
                    if not self._running or generation != self._generation:
                        break
                    paused = self._paused

                if paused:
                    # Wait for the pause to be lifted or the stop to arrive.
                    # The wait does not hold the action lock: a stop or a
                    # resume must not be delayed by the wait of this thread.
                    if self._stop_event.wait(timeout=0.25):
                        break
                    continue

                manager = self._resolve_manager()
                if manager is None:
                    # No engine attached: the loop stays alive and waits so an
                    # engine attached later is picked up by the thread.
                    if self._stop_event.wait(timeout=0.25):
                        break
                    continue

                try:
                    with self._action_lock:
                        # The tick and the check of the run flag are one
                        # atomic unit. A stop that is requested while this
                        # thread waits for the lock is therefore honoured
                        # before the next tick starts: the loop stops at the
                        # tick boundary and no tick is ever started behind
                        # the back of a stop.
                        if not self._running or generation != self._generation:
                            break
                        state = manager.state
                        if state != SimulationState.RUNNING:
                            manager.start()
                        manager.step(1)
                except Exception as err:  # noqa: BLE001
                    logger.exception("Runner tick failed: %s", err)
                    self._error = err
                    self._running = False
                    self._paused = False
                    self._stop_event.set()
                    break

                # Wall-clock pacing when speed_factor is configured.
                if self._speed_factor > 0.0:
                    target_duration_s = manager.config.tick_step_ns / 1e9 / self._speed_factor
                    elapsed_s = time.perf_counter() - last_pace_wall
                    sleep_s = target_duration_s - elapsed_s
                    if sleep_s > 0:
                        time.sleep(sleep_s)
                last_pace_wall = time.perf_counter()

        except Exception as err:
            logger.exception("Runner thread terminated unexpectedly: %s", err)
            self._error = err
        finally:
            with self._action_lock:
                # Only the current generation may clear the runner state. A
                # thread that has been superseded must leave the state of the
                # generation that replaced it untouched.
                if generation == self._generation:
                    self._running = False
                    self._paused = False
                    self._thread = None
