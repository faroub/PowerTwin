"""Fault Injection Engine — Controlled, Reproducible Fault & Disturbance Injection."""

import logging
import random
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.app.equipment.models import AlarmRecord, AlarmSeverity, OperatingState
from backend.app.models.grid.grid_model import DisturbanceType, GridDisturbance
from backend.app.topology.factory import BuiltPlantInstance

logger = logging.getLogger(__name__)


class FaultType(StrEnum):
    """Supported Controlled Fault Types."""

    BATTERY_CONTAINER_UNAVAILABLE = "BATTERY_CONTAINER_UNAVAILABLE"
    BMS_COMMUNICATION_LOSS = "BMS_COMMUNICATION_LOSS"
    PCS_COMMUNICATION_LOSS = "PCS_COMMUNICATION_LOSS"
    METER_COMMUNICATION_LOSS = "METER_COMMUNICATION_LOSS"
    FROZEN_MEASUREMENT = "FROZEN_MEASUREMENT"
    DELAYED_MEASUREMENT = "DELAYED_MEASUREMENT"
    INVALID_MEASUREMENT = "INVALID_MEASUREMENT"
    SENSOR_DRIFT = "SENSOR_DRIFT"
    OVERTEMPERATURE_SIMULATION = "OVERTEMPERATURE_SIMULATION"
    BATTERY_POWER_DERATING = "BATTERY_POWER_DERATING"
    PCS_POWER_DERATING = "PCS_POWER_DERATING"
    BREAKER_OPEN = "BREAKER_OPEN"
    GRID_DISCONNECTION = "GRID_DISCONNECTION"
    FREQUENCY_DISTURBANCE = "FREQUENCY_DISTURBANCE"
    VOLTAGE_DISTURBANCE = "VOLTAGE_DISTURBANCE"
    AUXILIARY_SYSTEM_FAILURE = "AUXILIARY_SYSTEM_FAILURE"


class FaultEventSpec(BaseModel):
    """Specification for a scheduled fault event."""

    fault_id: str = Field(description="Unique fault instance ID e.g. 'FAULT_001'")
    fault_type: FaultType
    target_equipment_id: str = Field(description="Target equipment ID e.g. 'CONTAINER_01'")
    trigger_timestamp_ns: int = Field(description="Simulation tick timestamp to inject fault")
    duration_ns: int | None = Field(default=None, description="Fault duration in ns")
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int = Field(default=42, description="Random seed for deterministic reproducibility")
    is_active: bool = Field(default=False)


class FaultAuditRecord(BaseModel):
    """Audit log entry for injected fault events."""

    timestamp_ns: int
    fault_id: str
    fault_type: FaultType
    target_equipment_id: str
    action: str  # INJECTED, CLEARED
    details: str


class FaultInjectionEngine:
    """Dedicated Fault Injection Engine operating on simulation instances only."""

    def __init__(self, seed: int = 42) -> None:
        self.seed: int = seed
        self.rng = random.Random(seed)
        self.scheduled_faults: list[FaultEventSpec] = []
        self.active_faults: dict[str, FaultEventSpec] = {}
        self.audit_records: list[FaultAuditRecord] = []

    def schedule_fault(self, fault: FaultEventSpec) -> None:
        """Schedule a fault for injection during simulation execution."""
        self.scheduled_faults.append(fault)

    def process_tick(self, current_time_ns: int, plant: BuiltPlantInstance) -> None:
        """Process fault schedule against current simulation clock timestamp."""
        # 1. Trigger scheduled faults
        for fault in list(self.scheduled_faults):
            if not fault.is_active and current_time_ns >= fault.trigger_timestamp_ns:
                self._inject_fault(fault, current_time_ns, plant)
                self.scheduled_faults.remove(fault)

        # 2. Clear expired temporary faults
        for fault_id, fault in list(self.active_faults.items()):
            if fault.duration_ns is not None:
                expiry_ts = fault.trigger_timestamp_ns + fault.duration_ns
                if current_time_ns >= expiry_ts:
                    self.clear_fault(fault_id, current_time_ns, plant)

    def _inject_fault(
        self, fault: FaultEventSpec, current_time_ns: int, plant: BuiltPlantInstance
    ) -> None:
        """Inject specific fault into simulated plant components."""
        fault.is_active = True
        self.active_faults[fault.fault_id] = fault

        logger.warning(
            "Injecting fault '%s' (%s) into equipment '%s' at t=%d ns",
            fault.fault_id,
            fault.fault_type,
            fault.target_equipment_id,
            current_time_ns,
        )

        eq_id = fault.target_equipment_id
        ft = fault.fault_type

        # Dispatch fault logic to simulated model instances
        if ft == FaultType.BATTERY_CONTAINER_UNAVAILABLE:
            for b in plant.battery_systems:
                if b.equipment_id == eq_id:
                    b.is_available = False
                    b.operating_state = OperatingState.FAULTED

        elif ft == FaultType.BMS_COMMUNICATION_LOSS:
            for bms in plant.bms_units:
                if bms.equipment_id == eq_id or bms.equipment_id == f"BMS_{eq_id}":
                    bms.is_available = False
                    bms.operating_state = OperatingState.FAULTED
                    bms.active_alarms.append(
                        AlarmRecord(
                            alarm_id=f"COMM_LOSS_{fault.fault_id}",
                            source_id=bms.equipment_id,
                            severity=AlarmSeverity.FAULT,
                            code="BMS_COMMUNICATION_LOSS",
                            description="BMS Communication connection lost",
                            timestamp_ns=current_time_ns,
                        )
                    )

        elif ft == FaultType.PCS_COMMUNICATION_LOSS:
            for pcs in plant.pcs_units:
                if pcs.equipment_id == eq_id:
                    pcs.is_available = False
                    pcs.operating_state = OperatingState.FAULTED

        elif ft == FaultType.OVERTEMPERATURE_SIMULATION:
            temp_c = fault.parameters.get("temperature_c", 65.0)
            for bms in plant.bms_units:
                if bms.equipment_id == eq_id or bms.equipment_id == f"BMS_{eq_id}":
                    bms.evaluate_protection(1000.0, 0.0, 50.0, temp_c)

        elif ft == FaultType.BREAKER_OPEN:
            for swg in plant.switchgear:
                if swg.equipment_id == eq_id or eq_id == "ALL":
                    swg.trip_breaker("E_STOP_TRIP", "Fault Injection Engine Breaker Trip")

        elif ft == FaultType.GRID_DISCONNECTION:
            dist = GridDisturbance(
                disturbance_type=DisturbanceType.GRID_DISCONNECTION,
                start_time_ns=current_time_ns,
            )
            plant.grid.apply_disturbance(dist)

        elif ft == FaultType.FREQUENCY_DISTURBANCE:
            f_hz = fault.parameters.get("frequency_hz", 59.5)
            f_dev = f_hz - plant.grid.config.nominal_frequency_hz
            dist = GridDisturbance(
                disturbance_type=DisturbanceType.FREQUENCY_STEP,
                start_time_ns=current_time_ns,
                magnitude=f_dev,
            )
            plant.grid.apply_disturbance(dist)

        elif ft == FaultType.VOLTAGE_DISTURBANCE:
            v_dev = fault.parameters.get("voltage_dev_pct", -5.0)
            v_mag = (v_dev / 100.0) * plant.grid.config.nominal_voltage_v
            dist = GridDisturbance(
                disturbance_type=DisturbanceType.VOLTAGE_STEP,
                start_time_ns=current_time_ns,
                magnitude=v_mag,
            )
            plant.grid.apply_disturbance(dist)

        # Audit Record
        self.audit_records.append(
            FaultAuditRecord(
                timestamp_ns=current_time_ns,
                fault_id=fault.fault_id,
                fault_type=ft,
                target_equipment_id=eq_id,
                action="INJECTED",
                details=f"Fault '{ft}' injected into '{eq_id}'",
            )
        )

    def clear_fault(self, fault_id: str, current_time_ns: int, plant: BuiltPlantInstance) -> bool:
        """Clear active fault and restore equipment availability."""
        if fault_id not in self.active_faults:
            return False

        fault = self.active_faults.pop(fault_id)
        fault.is_active = False
        eq_id = fault.target_equipment_id

        logger.info(
            "Clearing fault '%s' on equipment '%s' at t=%d ns", fault_id, eq_id, current_time_ns
        )

        for b in plant.battery_systems:
            if b.equipment_id == eq_id:
                b.is_available = True
                b.operating_state = OperatingState.STANDBY

        for bms in plant.bms_units:
            if bms.equipment_id == eq_id or bms.equipment_id == f"BMS_{eq_id}":
                bms.clear_faults()
                bms.is_available = True

        for pcs in plant.pcs_units:
            if pcs.equipment_id == eq_id:
                pcs.clear_faults()
                pcs.is_available = True

        for swg in plant.switchgear:
            if swg.equipment_id == eq_id:
                swg.clear_faults()

        self.audit_records.append(
            FaultAuditRecord(
                timestamp_ns=current_time_ns,
                fault_id=fault.fault_id,
                fault_type=fault.fault_type,
                target_equipment_id=eq_id,
                action="CLEARED",
                details=f"Fault '{fault.fault_type}' cleared on '{eq_id}'",
            )
        )
        return True
