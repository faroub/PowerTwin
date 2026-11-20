"""Small Example Simulation with Two Independent Dummy Components.

Demonstrates multi-rate execution, event emission, deterministic random generation,
and shared state updates using the PowerTwin simulation engine foundation.
"""

from backend.app.simulation.config import SimulationConfiguration
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.manager import SimulationRunManager
from backend.app.simulation.task import SimulationTask


class DummyPowerGeneratorTask(SimulationTask):
    """Dummy Generator Component running in Phase 1 (Environment) at 100 Hz (every 1 tick)."""

    def __init__(self, base_power_w: float = 100_000.0) -> None:
        super().__init__(
            name="DummyPowerGenerator",
            phase=1,
            priority=10,
            interval_ticks=1,
        )
        self.base_power_w: float = base_power_w

    def execute(self, ctx: SimulationContext) -> None:
        # Add deterministic Gaussian noise using seeded RNG
        noise_w = ctx.random.gauss(mu=0.0, sigma=1000.0)
        current_power_w = self.base_power_w + noise_w

        # Store in shared state bus
        ctx.shared_state["p_gen_w"] = current_power_w

        # Emit telemetry event
        ctx.emit_event(
            name="POWER_GENERATED",
            source=self.name,
            payload={"power_w": current_power_w},
        )


class DummyLoadConsumerTask(SimulationTask):
    """Dummy Load Component running in Phase 5 (Auxiliary) at 50 Hz (every 2 ticks)."""

    def __init__(self, load_power_w: float = 40_000.0) -> None:
        super().__init__(
            name="DummyLoadConsumer",
            phase=5,
            priority=10,
            interval_ticks=2,
        )
        self.load_power_w: float = load_power_w

    def execute(self, ctx: SimulationContext) -> None:
        p_gen = ctx.shared_state.get("p_gen_w", 0.0)
        net_power_w = p_gen - self.load_power_w
        ctx.shared_state["net_power_w"] = net_power_w

        ctx.emit_event(
            name="NET_POWER_CALCULATED",
            source=self.name,
            payload={"net_power_w": net_power_w},
        )


def create_example_simulation(seed: int = 42) -> SimulationRunManager:
    """Factory creating an instance of the example simulation."""
    config = SimulationConfiguration(
        tick_step_ns=10_000_000,  # 10 ms step
        speed_factor=0.0,  # Max speed headless
        random_seed=seed,
    )
    runner = SimulationRunManager(config=config)
    runner.register_task(DummyPowerGeneratorTask(base_power_w=100_000.0))
    runner.register_task(DummyLoadConsumerTask(load_power_w=40_000.0))
    return runner
