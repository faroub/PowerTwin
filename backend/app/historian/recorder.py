"""Application-layer recorder that feeds the historian from the running plant.

The historian subsystem (ring buffer, disk overflow, database flush) and its
read-only query API were implemented and unit-tested long before anything
called them. This module is the missing half: it turns the plant's live state
into historian rows.

Why it lives here and not in the simulation engine
---------------------------------------------------

``AGENTS.md`` §3 requires the simulation engine to stay independent of the
database, the HMI and the manufacturer-specific implementations. The engine
therefore knows nothing about the historian: it only knows the
``SimulationTask`` interface, which every scheduled task implements. The
recorder lives outside the simulation package and registers *itself* as a
task, so the dependency runs recorder -> engine and never engine -> database.

The recorder never holds a database session. It writes into the historian's
non-blocking ring buffer from the simulation thread; the flush to the database
happens in the application layer, on the event loop, with a session it opens
itself.

Why it samples on tick boundaries
---------------------------------

``AGENTS.md`` §6 forbids relying on uncontrolled wall-clock timing for the
simulation. A recorder driven by a wall-clock timer would produce a series
that depends on how fast the host happened to be, and a replay would not
reproduce it. The recorder is therefore a scheduled task with an
``interval_ticks`` decimation, so the sample points are a function of the
simulation tick and the recorded series stays faithful to the run.

Why it cannot break the simulation
----------------------------------

``HistorianService.record_telemetry`` never blocks: it puts the payload on a
bounded queue and, when the queue is full, writes the payload to the
historian's append-only overflow file instead. A database that is down or slow
therefore cannot stall a tick. The recorder's own sampling is wrapped so that
a defect in it is reported as an error and never propagates into the tick that
was recording.
"""

import logging
import threading
from typing import Any

from backend.app.controllers.command_log import CommandAuditEntry, ControlCommandLog
from backend.app.equipment.models import AlarmRecord, QualityFlag, UniversalEquipmentState
from backend.app.historian.service import HistorianService
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.task import SimulationTask

logger = logging.getLogger(__name__)

# The recorder samples after every physics task has updated the models for the
# tick, so the values it records are the ones the tick produced. Phase 6 is
# the last phase the scheduler accepts.
RECORDER_PHASE = 6

# A priority below every other task in the phase, so the recorder observes a
# settled plant.
RECORDER_PRIORITY = 100

# The historian records one row per measurement, so a plant with many
# measurements produces many rows per sample. The row cap keeps a single
# sample from silently flooding the buffer.
MAX_ROWS_PER_SAMPLE = 5_000


class HistorianRecorder(SimulationTask):
    """Record the running plant's telemetry, alarms and commands into the historian.

    The recorder is a scheduled task, so it samples on deterministic tick
    boundaries. It writes into the historian's non-blocking buffer and never
    touches the database itself.
    """

    def __init__(
        self,
        plant: Any,
        service: HistorianService,
        run_id: str,
        interval_ticks: int = 10,
    ) -> None:
        super().__init__(
            name="HISTORIAN_RECORDER_TASK",
            phase=RECORDER_PHASE,
            priority=RECORDER_PRIORITY,
            interval_ticks=interval_ticks,
        )
        self._plant = plant
        self._service = service
        self._run_id = run_id
        # The alarms already recorded, so that a raise is written once and a
        # clear is written once. The dictionary is keyed by alarm identifier.
        self._known_alarms: dict[str, AlarmRecord] = {}
        self._lock = threading.Lock()
        self._sample_count = 0
        self._telemetry_rows = 0
        self._alarm_rows = 0
        self._command_rows = 0
        self._last_error: str | None = None

    # ------------------------------------------------------------------ #
    # Scheduled task
    # ------------------------------------------------------------------ #

    def execute(self, ctx: SimulationContext) -> None:
        """Sample the plant once and record what it holds.

        A failure here is logged and swallowed: a recording defect must never
        become a simulation fault. The historian's own buffer protects the
        data; the simulation protects itself.
        """
        try:
            self._sample(ctx)
        except Exception as err:  # noqa: BLE001
            self._record_error(str(err))
            logger.error("The historian recorder could not take a sample: %s", err, exc_info=True)

    def _sample(self, ctx: SimulationContext) -> None:
        timestamp_ns = ctx.current_tick_ns
        self._sample_count += 1

        rows = 0
        for state in self._equipment_states():
            rows += self._record_state(state, timestamp_ns)
            if rows >= MAX_ROWS_PER_SAMPLE:
                logger.warning(
                    "The historian sample reached the %d-row cap; the rest of the plant "
                    "was not recorded in this sample.",
                    MAX_ROWS_PER_SAMPLE,
                )
                break

        self._telemetry_rows += rows
        self._record_alarms(timestamp_ns)

    def _record_state(self, state: UniversalEquipmentState, timestamp_ns: int) -> int:
        """Record every measurement of one piece of equipment."""
        rows = 0
        for tag_id, point in state.measurements.items():
            self._service.record_telemetry(
                tag_id=tag_id,
                equipment_id=state.equipment_id,
                val_float=point.value,
                unit=point.unit,
                timestamp_ns=timestamp_ns,
                source_timestamp_ns=point.timestamp_ns,
                quality=point.quality.value,
                source_type="SIMULATED",
                simulation_run_id=self._run_id,
            )
            rows += 1
        return rows

    # ------------------------------------------------------------------ #
    # Alarms
    # ------------------------------------------------------------------ #

    def _record_alarms(self, timestamp_ns: int) -> None:
        """Record every alarm that was raised or cleared since the last sample.

        The plant keeps an alarm in its active list until it is cleared, so a
        raise is seen once and a clear is seen once. The historian's alarm row
        carries a ``cleared`` flag, but the recorder API only writes raised
        alarms; a clear is therefore written as its own event, with the code
        of the alarm it clears and a description that says so.
        """
        current: dict[str, AlarmRecord] = {}
        for state in self._equipment_states():
            for alarm in state.alarms:
                current[alarm.alarm_id] = alarm

        with self._lock:
            known = dict(self._known_alarms)
            self._known_alarms = current

        for alarm_id, alarm in current.items():
            if alarm_id in known:
                continue
            self._service.record_alarm(
                event_id=alarm.alarm_id,
                equipment_id=alarm.source_id,
                severity=alarm.severity.value,
                code=alarm.code,
                description=alarm.description,
                timestamp_ns=timestamp_ns,
                simulation_run_id=self._run_id,
            )
            self._alarm_rows += 1

        for alarm_id, alarm in known.items():
            if alarm_id in current:
                continue
            self._service.record_alarm(
                event_id=f"{alarm_id}_CLEARED",
                equipment_id=alarm.source_id,
                severity=alarm.severity.value,
                code=alarm.code,
                description=f"Alarm {alarm.code} was cleared.",
                timestamp_ns=timestamp_ns,
                simulation_run_id=self._run_id,
            )
            self._alarm_rows += 1

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    def record_command_entry(self, entry: CommandAuditEntry) -> None:
        """Record one command from the plant's control-command audit log.

        The command log is the platform's single write path for control
        actions: it already fans every entry out to the operator-action
        journal. The recorder subscribes to it rather than wrapping it, so a
        command is recorded exactly once and there is still one write path.
        """
        try:
            self._service.record_command(
                command_id=entry.command_id,
                requestor=entry.source_layer,
                target_equipment_id=entry.target_component,
                requested_value={
                    "action_name": entry.action_name,
                    "requested_value": entry.requested_value,
                },
                accepted_status=entry.status.value,
                rejection_reason=entry.reason,
                timestamp_ns=entry.timestamp_ns,
                resulting_response=entry.accepted_value,
                simulation_run_id=self._run_id,
            )
            self._command_rows += 1
        except Exception as err:  # noqa: BLE001
            self._record_error(str(err))
            logger.error("The historian could not record a command: %s", err, exc_info=True)

    def attach_to_plant(self) -> int:
        """Subscribe the recorder to every control-command log on the plant.

        Returns the number of logs the recorder subscribed to.
        """
        subscribed = 0
        for audit_log in self._control_logs():
            audit_log.add_sink(self.record_command_entry)
            subscribed += 1
        return subscribed

    def detach_from_plant(self) -> int:
        """Unsubscribe the recorder from every control-command log.

        A recorder that is detached must stop receiving commands, otherwise a
        replaced recorder would keep writing to the store beside its
        successor.
        """
        detached = 0
        for audit_log in self._control_logs():
            audit_log.remove_sink(self.record_command_entry)
            detached += 1
        return detached

    def _control_logs(self) -> list[ControlCommandLog]:
        """Collect the control-command logs that the plant's controllers own."""
        logs: list[ControlCommandLog] = []
        for holder in (
            getattr(self._plant, "equipment_controller", None),
            getattr(self._plant, "ems", None),
            getattr(self._plant, "ppc", None),
        ):
            audit_log = getattr(holder, "audit_log", None)
            if isinstance(audit_log, ControlCommandLog):
                logs.append(audit_log)
        return logs

    # ------------------------------------------------------------------ #
    # Plant access
    # ------------------------------------------------------------------ #

    def _equipment_states(self) -> list[UniversalEquipmentState]:
        """Return the current state of every piece of equipment on the plant.

        Every model on the plant publishes a ``UniversalEquipmentState``, so
        the recorder needs no knowledge of any individual model.
        """
        states: list[UniversalEquipmentState] = []
        for collection_name in (
            "battery_systems",
            "bms_units",
            "pcs_units",
            "transformers",
            "switchgear",
            "meters",
        ):
            for model in getattr(self._plant, collection_name, None) or []:
                state = self._state_of(model)
                if state is not None:
                    states.append(state)

        for attribute in ("poi", "grid"):
            model = getattr(self._plant, attribute, None)
            if model is None:
                continue
            state = self._state_of(model)
            if state is not None:
                states.append(state)
        return states

    def _state_of(self, model: Any) -> UniversalEquipmentState | None:
        """Return a model's published state, or nothing if it publishes none.

        A model that cannot publish its state is skipped and the defect is
        recorded in the recorder's status: one broken model must not cost the
        rest of the plant its sample, and the defect must not stay hidden.
        """
        get_state = getattr(model, "get_state", None)
        if not callable(get_state):
            return None
        try:
            state: UniversalEquipmentState = get_state()
        except Exception as err:  # noqa: BLE001
            self._record_error(str(err))
            logger.warning("A plant model could not publish its state: %s", err)
            return None
        return state

    def _record_error(self, message: str) -> None:
        """Remember the most recent recording defect for the status report."""
        with self._lock:
            self._last_error = message

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    @property
    def status(self) -> dict[str, Any]:
        """Describe what the recorder has recorded so far."""
        with self._lock:
            return {
                "run_id": self._run_id,
                "samples": self._sample_count,
                "telemetry_rows": self._telemetry_rows,
                "alarm_rows": self._alarm_rows,
                "command_rows": self._command_rows,
                "interval_ticks": self.interval_ticks,
                "last_error": self._last_error,
            }

    @property
    def service(self) -> HistorianService:
        """The historian service this recorder writes into."""
        return self._service

    @property
    def run_id(self) -> str:
        """The simulation run identifier carried on every recorded row."""
        return self._run_id

    @property
    def quality_default(self) -> QualityFlag:
        """The quality carried by a measurement that reports none of its own."""
        return QualityFlag.GOOD
