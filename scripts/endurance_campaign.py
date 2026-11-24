"""Run a long-duration endurance campaign against the PowerTwin simulation engine.

The nightly pipeline runs this campaign to answer three questions that a
normal unit test cannot:

* does the engine still produce **bit-identical** results after a long run,
  that is, does the determinism survive a large number of ticks,
* does the engine **drift** over time, for example through a state variable
  that is never reset,
* what is the **throughput** of the engine, so that a performance regression
  is visible in the nightly report.

The campaign is *simulation only*. It builds a plant from a YAML topology and
runs the deterministic engine against it. It never opens a socket, never
connects to a database and never addresses physical equipment.

Determinism check
-----------------
The campaign runs the same number of ticks twice with the same seed and
compares a fingerprint of the resulting engine snapshot. The fingerprint
covers the simulation timestamp, the tick count, the shared state and the
per-task state. The snapshot identifier and the wall-clock creation time are
excluded because they are deliberately non-deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CampaignResult",
    "DeterminismMismatch",
    "build_fingerprint",
    "main",
    "run_campaign",
]

DEFAULT_CONFIG = "configs/reference_10mw_20mwh.yaml"


class DeterminismMismatch(RuntimeError):
    """Raised when two runs with the same seed produce different results."""


@dataclass(frozen=True)
class CampaignResult:
    """The outcome of one endurance campaign run.

    Attributes:
        seed: The random seed the campaign ran with.
        ticks_requested: The number of ticks that were requested.
        ticks_executed: The number of ticks that were actually executed.
        tick_step_ns: The duration of one simulation tick in nanoseconds.
        simulated_seconds: The simulated duration of the campaign.
        wall_clock_seconds: The wall-clock duration of the campaign.
        ticks_per_second: The number of ticks executed per wall-clock second.
        fingerprint: The deterministic fingerprint of the final state.
    """

    seed: int
    ticks_requested: int
    ticks_executed: int
    tick_step_ns: int
    simulated_seconds: float
    wall_clock_seconds: float
    ticks_per_second: float
    fingerprint: str


def build_fingerprint(snapshot: Any) -> str:
    """Return a deterministic fingerprint of an engine snapshot.

    The snapshot identifier and the wall-clock creation time are excluded:
    they are non-deterministic by design and would mask a real difference.

    Args:
        snapshot: A :class:`~backend.app.simulation.snapshot.SimulationSnapshot`.

    Returns:
        The hexadecimal SHA-256 digest of the deterministic state.
    """
    payload = {
        "timestamp_ns": snapshot.timestamp_ns,
        "total_steps": snapshot.total_steps,
        "step_ns": snapshot.step_ns,
        "shared_state": snapshot.shared_state,
        "task_states": snapshot.task_states,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_plant(config_path: str) -> Any:
    """Build the reference plant and bring its equipment to the running state."""
    from backend.app.topology.factory import PlantTopologyFactory

    factory = PlantTopologyFactory()
    topology = factory.load_config_from_yaml(config_path)
    plant = factory.build_plant(topology)

    started = plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    if not started:
        msg = "The endurance campaign could not start the equipment of the plant."
        raise RuntimeError(msg)

    return plant


def run_campaign(
    *,
    ticks: int,
    seed: int,
    config_path: str = DEFAULT_CONFIG,
) -> CampaignResult:
    """Run one endurance campaign.

    Args:
        ticks: The number of ticks to execute.
        seed: The random seed. The same seed always produces the same result.
        config_path: Path of the plant topology YAML file.

    Returns:
        The result of the campaign.

    Raises:
        ValueError: If ``ticks`` is not strictly positive.
        RuntimeError: If the plant equipment could not be started.
    """
    if ticks <= 0:
        msg = f"The number of ticks must be strictly positive, got {ticks}."
        raise ValueError(msg)

    plant = _build_plant(config_path)
    engine = plant.simulation_engine

    # Apply the seed before any tick is executed so that every random process
    # in the plant draws from the same deterministic stream.
    engine.config.random_seed = seed
    engine.random.reseed(seed)
    engine.config.speed_factor = 0.0

    started = time.monotonic()
    ticks_executed = engine.run_headless(ticks)
    wall_clock = time.monotonic() - started

    snapshot = engine.create_snapshot()
    tick_step_ns = engine.config.tick_step_ns

    return CampaignResult(
        seed=seed,
        ticks_requested=ticks,
        ticks_executed=ticks_executed,
        tick_step_ns=tick_step_ns,
        simulated_seconds=ticks_executed * tick_step_ns / 1_000_000_000,
        wall_clock_seconds=wall_clock,
        ticks_per_second=(ticks_executed / wall_clock) if wall_clock > 0 else 0.0,
        fingerprint=build_fingerprint(snapshot),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the endurance campaign.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when the campaign passed, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Run a long-duration endurance campaign against the simulation engine."
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=36_000,
        help="Number of ticks to execute (default: 36000, that is 6 minutes at 100 Hz).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed of the campaign (default: 42).",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"Path of the plant topology YAML file (default: {DEFAULT_CONFIG}).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=2,
        help="Number of runs used for the determinism check (default: 2).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path of a JSON report file.",
    )
    args = parser.parse_args(argv)

    if args.repeats < 1:
        print("ERROR: --repeats must be at least 1.", file=sys.stderr)
        return 1

    try:
        results = [
            run_campaign(ticks=args.ticks, seed=args.seed, config_path=args.config)
            for _ in range(args.repeats)
        ]
    except (ValueError, RuntimeError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    for index, result in enumerate(results, start=1):
        print(
            f"Run {index}/{len(results)}: {result.ticks_executed} ticks, "
            f"{result.simulated_seconds:.1f} simulated seconds, "
            f"{result.wall_clock_seconds:.2f} wall-clock seconds, "
            f"{result.ticks_per_second:.0f} ticks/s, "
            f"fingerprint {result.fingerprint[:16]}"
        )

    fingerprints = {result.fingerprint for result in results}
    if len(fingerprints) != 1:
        print(
            "ERROR: The campaign is not deterministic: the runs with seed "
            f"{args.seed} produced {len(fingerprints)} different results.",
            file=sys.stderr,
        )
        return 1

    if any(result.ticks_executed != args.ticks for result in results):
        executed = {result.ticks_executed for result in results}
        print(
            f"ERROR: The campaign executed {executed} ticks instead of the "
            f"requested {args.ticks}; the engine stopped early.",
            file=sys.stderr,
        )
        return 1

    print(f"The campaign is deterministic for seed {args.seed}.")

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps([asdict(result) for result in results], indent=2),
            encoding="utf-8",
        )
        print(f"The campaign report was written to {args.report}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
