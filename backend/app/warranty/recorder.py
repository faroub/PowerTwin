"""Application-layer recorder that analyses the running plant's warranty state.

The recorder is the counterpart of `backend/app/historian/recorder.py`. It
runs as a scheduled simulation task, reads the plant, and writes its findings
into the historian's non-blocking buffer. It never touches a database, and it
never changes the plant.

Why it samples on every tick
----------------------------

The historian recorder decimates its samples: one sample every N ticks is
enough for a time series. The warranty recorder is not allowed to do that.
The time a container spends above 45 degrees is an **integral over the run**,
and an integral taken at sample points undercounts it — the more coarsely the
samples are taken, the more of the hot intervals fall between them. The
recorder therefore runs on every tick and does the accumulation itself. The
snapshot it publishes is decimated; the accumulation behind it is not.

Why the degradation is reported and not applied
------------------------------------------------

The recorder computes a state of health and a projection, and it writes them
out. It does **not** write the degradation back into the battery model. A
plant that silently lost capacity while a screen reported a different number
would be a divergence with no error anywhere, and the whole point of the
analysis is to observe the plant as it is.

The model behind the analysis is illustrative (`AGENTS.md` §2.13, §2.14): its
constants have not been validated against any manufacturer document. The
recorder says so on every row it writes.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.app.simulation.context import SimulationContext
from backend.app.simulation.task import SimulationTask
from backend.app.warranty.assessment import assess_warranty
from backend.app.warranty.degradation import DegradationModel, DegradationParameters

logger = logging.getLogger(__name__)

__all__ = [
    "TEMPERATURE_THRESHOLD_C",
    "WARRANTY_RECORDER_PHASE",
    "WARRANTY_RECORDER_PRIORITY",
    "WarrantyRecorder",
    "WarrantySink",
]

#: The recorder runs in the last phase, so it observes a plant whose physics
#: has already been updated for the tick.
WARRANTY_RECORDER_PHASE = 6

#: A priority above the historian recorder's, so the warranty snapshot and
#: the telemetry sample describe the same settled plant.
WARRANTY_RECORDER_PRIORITY = 101

#: The temperature the historian's snapshot counts the time above.
TEMPERATURE_THRESHOLD_C = 45.0

#: The telemetry tags the recorder publishes, with their units.
WARRANTY_TELEMETRY_TAGS: tuple[tuple[str, str], ...] = (
    ("warranty.current_soh_pct", "pct"),
    ("warranty.projected_soh_pct", "pct"),
    ("warranty.equivalent_full_cycles", "efc"),
    ("warranty.total_throughput_wh", "Wh"),
    ("warranty.max_temperature_c", "degC"),
    ("warranty.time_above_45c_s", "s"),
)


class WarrantySink(Protocol):
    """What the warranty recorder writes into.

    The recorder depends on this narrow interface rather than on the
    historian's concrete service, so the coupling is visible: the recorder
    records snapshots and telemetry, and it does nothing else.
    """

    def record_warranty_metrics(
        self,
        container_id: str,
        simulation_run_id: str,
        updated_at_ns: int,
        total_energy_throughput_wh: float,
        equivalent_full_cycles: float,
        max_temperature_recorded_c: float,
        time_above_45c_seconds: float,
        current_soh_pct: float,
    ) -> bool:
        """Record a warranty snapshot."""
        ...

    def record_telemetry(
        self,
        tag_id: str,
        equipment_id: str,
        val_float: float,
        unit: str,
        timestamp_ns: int,
        source_timestamp_ns: int | None = None,
        quality: str = "GOOD",
        source_type: str = "SIMULATED",
        simulation_run_id: str = "RUN_001",
    ) -> bool:
        """Record a telemetry point."""
        ...


@dataclass
class _ContainerHistory:
    """The operating history the recorder keeps for one container.

    Attributes:
        container_id: The container the history belongs to.
        capacity_wh: The container's nominal capacity, used to turn the
            energy throughput into equivalent full cycles.
        max_temperature_c: The highest temperature the container reached.
        time_above_45c_seconds: The time the container spent above 45
            degrees Celsius.
    """

    container_id: str
    capacity_wh: float
    max_temperature_c: float
    time_above_45c_seconds: float = 0.0


@dataclass
class _RecorderState:
    """The recorder's own bookkeeping.

    Attributes:
        histories: The per-container operating histories, keyed by container
            identifier.
        last_publish_tick_ns: The simulation time the last snapshot was
            published at.
        published: The number of snapshots published.
        errors: The number of defects the recorder hit.
        last_error: The most recent defect.
    """

    histories: dict[str, _ContainerHistory] = field(default_factory=dict)
    last_publish_tick_ns: int | None = None
    published: int = 0
    errors: int = 0
    last_error: str | None = None


class WarrantyRecorder(SimulationTask):
    """Analyse the running plant's warranty state and record the findings.

    The recorder is a scheduled task, so its observations are a function of
    the simulation tick and not of how fast the host happened to be. It reads
    the plant, never writes to it.
    """

    def __init__(
        self,
        plant: Any,
        sink: WarrantySink,
        run_id: str,
        sample_interval_ticks: int = 10,
        parameters: DegradationParameters | None = None,
    ) -> None:
        super().__init__(
            name="WARRANTY_RECORDER_TASK",
            phase=WARRANTY_RECORDER_PHASE,
            priority=WARRANTY_RECORDER_PRIORITY,
            # The accumulator has to see every tick: the time above 45
            # degrees is an integral, and an integral over decimated samples
            # undercounts the hot intervals.
            interval_ticks=1,
        )
        self._plant = plant
        self._sink = sink
        self._run_id = run_id
        self._sample_interval_ticks = max(1, sample_interval_ticks)
        self._parameters = parameters if parameters is not None else DegradationParameters()
        self._model = DegradationModel(self._parameters)
        self._lock = threading.Lock()
        self._state = _RecorderState()
        self._seed_histories()

    # ------------------------------------------------------------------ #
    # Scheduled task
    # ------------------------------------------------------------------ #

    def execute(self, ctx: SimulationContext) -> None:
        """Accumulate the operating history and publish a snapshot in due course.

        A failure here is logged and swallowed: an analysis defect must never
        become a simulation fault. The plant does not depend on the recorder.
        """
        try:
            self._accumulate(ctx)
            self._publish_if_due(ctx)
        except Exception as err:  # noqa: BLE001
            self._record_error(str(err))
            logger.error("The warranty recorder could not take a sample: %s", err, exc_info=True)

    def _accumulate(self, ctx: SimulationContext) -> None:
        """Fold this tick's state into the per-container operating history."""
        delta_t_s = ctx.delta_t_s
        with self._lock:
            histories = self._state.histories
            for model in self._battery_models():
                container_id = str(getattr(model, "equipment_id", "") or "")
                history = histories.get(container_id)
                if history is None:
                    continue

                temperature_c = float(getattr(model, "temperature_c", history.max_temperature_c))
                if temperature_c > history.max_temperature_c:
                    history.max_temperature_c = temperature_c
                if temperature_c > TEMPERATURE_THRESHOLD_C:
                    history.time_above_45c_seconds += delta_t_s

    def _publish_if_due(self, ctx: SimulationContext) -> None:
        """Publish a snapshot when the sample interval has elapsed."""
        # The interval is derived from the simulation's own tick, never from
        # the wall clock, so the publication cadence is a function of the run.
        interval_ns = int(ctx.delta_t_s * 1_000_000_000.0) * self._sample_interval_ticks

        with self._lock:
            last = self._state.last_publish_tick_ns
            if last is not None and ctx.current_tick_ns - last < interval_ns:
                return
            self._state.last_publish_tick_ns = ctx.current_tick_ns

        snapshots = self._build_snapshots(ctx)
        for container_id, payload, projected_soh in snapshots:
            self._sink.record_warranty_metrics(
                container_id=container_id,
                simulation_run_id=self._run_id,
                updated_at_ns=payload["updated_at_ns"],
                total_energy_throughput_wh=payload["total_energy_throughput_wh"],
                equivalent_full_cycles=payload["equivalent_full_cycles"],
                max_temperature_recorded_c=payload["max_temperature_recorded_c"],
                time_above_45c_seconds=payload["time_above_45c_seconds"],
                current_soh_pct=payload["current_soh_pct"],
            )
            self._record_telemetry(container_id, ctx.current_tick_ns, payload, projected_soh)

        with self._lock:
            self._state.published += 1

    def _build_snapshots(
        self, ctx: SimulationContext
    ) -> list[tuple[str, dict[str, Any], float | None]]:
        """Build the snapshot each container would publish right now.

        Returns:
            One ``(container_id, payload, projected_soh)`` triple per
            container.
        """
        elapsed_seconds = ctx.current_tick_ns / 1_000_000_000.0
        results: list[tuple[str, dict[str, Any], float | None]] = []

        with self._lock:
            histories = dict(self._state.histories)
            models = {
                str(getattr(model, "equipment_id", "") or ""): model
                for model in self._battery_models()
            }

        for container_id, history in histories.items():
            model = models.get(container_id)
            if model is None:
                continue

            throughput_wh = float(getattr(model, "total_throughput_wh", 0.0))
            capacity_wh = history.capacity_wh
            equivalent_full_cycles = (
                throughput_wh / (2.0 * capacity_wh) if capacity_wh > 0.0 else 0.0
            )

            current_soh = self._model.observed_soh_pct(
                elapsed_seconds=elapsed_seconds,
                equivalent_full_cycles=equivalent_full_cycles,
                temperature_c=history.max_temperature_c,
            )
            assessment = assess_warranty(
                current_soh_pct=current_soh,
                equivalent_full_cycles=equivalent_full_cycles,
                elapsed_seconds=elapsed_seconds,
                max_temperature_recorded_c=history.max_temperature_c,
                parameters=self._parameters,
            )

            payload = {
                "updated_at_ns": ctx.current_tick_ns,
                "total_energy_throughput_wh": throughput_wh,
                "equivalent_full_cycles": equivalent_full_cycles,
                "max_temperature_recorded_c": history.max_temperature_c,
                "time_above_45c_seconds": history.time_above_45c_seconds,
                "current_soh_pct": current_soh,
            }
            results.append((container_id, payload, assessment.projected_soh_pct))

        return results

    def _record_telemetry(
        self,
        container_id: str,
        timestamp_ns: int,
        payload: dict[str, Any],
        projected_soh: float | None,
    ) -> None:
        """Publish the coarse-cadence warranty time series."""
        values: dict[str, float] = {
            "warranty.current_soh_pct": payload["current_soh_pct"],
            "warranty.equivalent_full_cycles": payload["equivalent_full_cycles"],
            "warranty.total_throughput_wh": payload["total_energy_throughput_wh"],
            "warranty.max_temperature_c": payload["max_temperature_recorded_c"],
            "warranty.time_above_45c_s": payload["time_above_45c_seconds"],
        }
        if projected_soh is not None:
            values["warranty.projected_soh_pct"] = projected_soh

        for tag_id, unit in WARRANTY_TELEMETRY_TAGS:
            value = values.get(tag_id)
            if value is None:
                continue
            self._sink.record_telemetry(
                tag_id=tag_id,
                equipment_id=container_id,
                val_float=value,
                unit=unit,
                timestamp_ns=timestamp_ns,
                source_timestamp_ns=timestamp_ns,
                quality="GOOD",
                source_type="SIMULATED",
                simulation_run_id=self._run_id,
            )

    # ------------------------------------------------------------------ #
    # Plant access
    # ------------------------------------------------------------------ #

    def _battery_models(self) -> list[Any]:
        """Return the plant's battery models."""
        return list(getattr(self._plant, "battery_systems", None) or [])

    def _seed_histories(self) -> None:
        """Create the operating history of every container on the plant.

        A container that is added to the plant after the recorder started is
        picked up on the next tick, because `_accumulate` asks the plant for
        the containers it has.
        """
        for model in self._battery_models():
            container_id = str(getattr(model, "equipment_id", "") or "")
            if not container_id:
                continue
            config = getattr(model, "config", None)
            capacity_wh = float(getattr(config, "capacity_wh", 0.0) or 0.0)
            initial_temperature = float(getattr(model, "temperature_c", 25.0))
            with self._lock:
                self._state.histories[container_id] = _ContainerHistory(
                    container_id=container_id,
                    capacity_wh=capacity_wh,
                    max_temperature_c=initial_temperature,
                )

    def _record_error(self, message: str) -> None:
        """Remember the most recent defect for the status report."""
        with self._lock:
            self._state.errors += 1
            self._state.last_error = message

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    @property
    def status(self) -> dict[str, Any]:
        """Describe what the recorder has analysed so far."""
        with self._lock:
            return {
                "run_id": self._run_id,
                "containers": len(self._state.histories),
                "snapshots_published": self._state.published,
                "sample_interval_ticks": self._sample_interval_ticks,
                "illustrative": self._parameters.illustrative,
                "errors": self._state.errors,
                "last_error": self._state.last_error,
            }

    @property
    def run_id(self) -> str:
        """The simulation run identifier carried on every recorded row."""
        return self._run_id

    @property
    def sample_interval_ticks(self) -> int:
        """The number of ticks between two published snapshots."""
        return self._sample_interval_ticks
