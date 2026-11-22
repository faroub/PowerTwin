"""Simulation Runner — authoritative, thread-safe execution loop.

An active simulation needs more than a state machine: ``start()`` must begin a
continuous, paced tick loop, and the API must be able to control the loop
without ever blocking the FastAPI event loop.

Execution order is owned by ``SimulationRunManager`` (scheduler + clock), this
runner owns the *thread* and the *control* surface:

    * a non-blocking action queue so every API call returns immediately
    * deterministic wall-clock pacing around the fixed ``tick_step_ns``
    * isolated reset, start, pause, resume, single-step, and shutdown paths
    * clean teardown on application shutdown
"""

import logging
import threading
import time
from collections import deque
from typing import Any

from backend.app.simulation.manager import SimulationRunManager

logger = logging.getLogger(__name__)


class SimulationRunner:
    """API-facing simulation runner backed by a dedicated execution thread."""

    def __init__(self, manager: SimulationRunManager, plant: Any = None) -> None:
        self._manager: SimulationRunManager = manager
        self._plant: Any = plant

        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._paused: bool = False
        self._stop_event: threading.Event = threading.Event()
        self._action_queue: deque[dict[str, Any]] = deque()
        self._action_lock = threading.Lock()

        self._error: Exception | None = None
        self._started_at_wall: float = 0.0
        self._speed_factor: float = 1.0

    # ---------------------------------------------------------------- #
    # Public lifecycle
    # ---------------------------------------------------------------- #

    @property
    def manager(self) -> SimulationRunManager:
        """Underlying simulation engine instance."""
        return self._manager

    @property
    def state(self) -> Any:
        """Current engine state (mirrors SimulationRunManager.state)."""
        return self._manager.state

    @property
    def is_running(self) -> bool:
        """True while the execution thread is actively driving ticks."""
        return self._running

    @property
    def speed_factor(self) -> float:
        return self._speed_factor

    def start(self) -> None:
        """Start or resume the continuous execution loop."""
        if self._running and not self._paused:
            logger.warning("Simulation runner is already running.")
            return

        with self._action_lock:
            if self._running and not self._paused:
                return
            self._running = True
            self._paused = False
            self._stop_event.clear()

        self._manager.start()
        self._started_at_wall = time.perf_counter()

        if not self._running:
            self._running = True

        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._execution_loop,
                name="PowerTwin-simulation-run",
                daemon=True,
            )
            self._thread.start()

    def pause(self) -> None:
        """Pause the execution loop at the next tick boundary."""
        with self._action_lock:
            self._paused = True
        self._manager.pause()

    def resume(self) -> None:
        """Resume a paused execution loop."""
        with self._action_lock:
            self._paused = False
        self._manager.resume()

    def stop(self) -> None:
        """Stop the execution loop and mark the engine as stopped."""
        with self._action_lock:
            self._running = False
            self._paused = False
            self._stop_event.set()
        self._manager.stop()

    def stop_with_timeout(self, timeout_s: float = 10.0) -> bool:
        """Stop the runner and wait for the thread to finish cleanly."""
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            return not self._thread.is_alive()
        return True

    def shutdown(self) -> None:
        """Graceful teardown: stop the loop, reset the engine, clean up resources."""
        self.stop_with_timeout()
        try:
            self._manager.reset()
        except Exception as err:
            logger.error("Error resetting simulation engine on shutdown: %s", err)

    def single_step(self) -> list[str]:
        """Execute exactly one tick outside the loop thread."""
        return self._enqueue_action_now("STEP", steps=1)

    def step(self, num_ticks: int = 1) -> list[str]:
        """Execute num_ticks ticks outside the loop thread."""
        return self._enqueue_action_now("STEP", steps=num_ticks)

    def run_headless(self, max_ticks: int) -> int:
        """Run max_ticks at maximum speed (no wall-clock pacing)."""
        return self._manager.run_headless(max_ticks)

    def set_speed_factor(self, multiplier: float) -> None:
        """Update simulation wall-clock speed pacing factor."""
        if multiplier < 0.0:
            raise ValueError("Speed factor multiplier must be >= 0.0")
        self._speed_factor = multiplier
        self._manager.set_speed_factor(multiplier)

    def reset(self) -> None:
        """Reset the engine to its initial conditions."""
        self.stop()
        self._manager.reset()

    def create_snapshot(self) -> Any:
        """Capture engine state snapshot."""
        return self._manager.create_snapshot()

    def restore_snapshot(self, snapshot: Any) -> None:
        """Restore engine state from a snapshot."""
        self._manager.restore_snapshot(snapshot)

    # ---------------------------------------------------------------- #
    # Action queue
    # ---------------------------------------------------------------- #

    def _enqueue_action_now(self, action: str, **kwargs: Any) -> list[str]:
        """Execute an action immediately (used by the API layer)."""
        with self._action_lock:
            self._action_queue.append(
                {"action": action, "kwargs": kwargs, "queue_time_ns": time.perf_counter_ns()}
            )
        logger.debug("Enqueued simulation action '%s'", action)

        # Direct execution for one-shot commands so the API never queues a
        # tick it must actually run.
        if action == "STEP":
            steps = max(1, kwargs.get("steps", 1))
            return self._manager.step(steps)
        if action == "START":
            self.start()
        elif action == "PAUSE":
            self.pause()
        elif action == "RESUME":
            self.resume()
        elif action == "STOP":
            self.stop()
        elif action == "RESET":
            self.reset()
        elif action == "SET_SPEED":
            speed_factor = kwargs.get("speed_factor")
            if speed_factor is None:
                logger.warning("SET_SPEED action received without a speed factor.")
            else:
                self.set_speed_factor(speed_factor)
        return []

    def _process_actions(self) -> None:
        """Drain the API action queue under a lock."""
        with self._action_lock:
            if not self._action_queue:
                return
            actions = list(self._action_queue)
            self._action_queue.clear()

        for item in actions:
            action = item["action"]
            kwargs = item["kwargs"]
            try:
                if action == "STEP":
                    self._manager.step(max(1, kwargs.get("steps", 1)))
                elif action == "START":
                    self.start()
                elif action == "PAUSE":
                    self.pause()
                elif action == "RESUME":
                    self.resume()
                elif action == "STOP":
                    self.stop()
                elif action == "RESET":
                    self.reset()
                elif action == "SET_SPEED":
                    self.set_speed_factor(kwargs.get("speed_factor"))
                else:
                    logger.warning("Unknown simulation action: %r", action)
            except Exception as err:  # noqa: BLE001
                logger.error("Simulation action %r failed: %s", action, err)
                self._error = err
                self._running = False
                self._paused = False
                self._stop_event.set()

    # ---------------------------------------------------------------- #
    # Execution loop
    # ---------------------------------------------------------------- #

    def _execution_loop(self) -> None:
        """Loop thread: advance the engine at the configured simulation rate."""
        try:
            last_pace_wall = time.perf_counter()
            while True:
                with self._action_lock:
                    if not self._running:
                        break
                    if self._paused:
                        # Wait for the pause to be lifted or the stop to arrive.
                        if self._stop_event.wait(timeout=0.25):
                            break
                        continue

                # Any API enqueued action takes priority over the loop.
                if self._action_queue:
                    self._process_actions()
                    if not self._running:
                        break
                    continue

                try:
                    self._manager.step(1)
                except Exception as err:  # noqa: BLE001
                    logger.exception("Runner tick failed: %s", err)
                    self._error = err
                    self._running = False
                    self._paused = False
                    self._stop_event.set()
                    with self._action_lock:
                        self._running = False
                    break

                # Wall-clock pacing when speed_factor is configured.
                if self._speed_factor > 0.0:
                    target_duration_s = (
                        self._manager.config.tick_step_ns / 1e9
                    ) / self._speed_factor
                    elapsed_s = time.perf_counter() - last_pace_wall
                    sleep_s = target_duration_s - elapsed_s
                    if sleep_s > 0:
                        time.sleep(sleep_s)
                last_pace_wall = time.perf_counter()

        except Exception as err:
            logger.exception("Runner thread terminated unexpectedly: %s", err)
            self._error = err
        finally:
            self._running = False
            self._paused = False
            self._thread = None
