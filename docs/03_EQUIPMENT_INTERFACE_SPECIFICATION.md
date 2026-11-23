# PowerTwin — Equipment Interface Specification

## 1. Overview

This document specifies the standardized, typed Python interfaces for all equipment models in the PowerTwin platform. All models must implement these interfaces to ensure plug-and-play interoperability across generic core models and vendor-specific plugins.

---

## 2. Common Data Structures & Enums

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class QualityFlag(str, Enum):
    GOOD = "GOOD"
    BAD = "BAD"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"


class TelemetryPoint(BaseModel):
    value: float
    unit: str
    timestamp_ns: int = Field(description="Simulation tick timestamp in nanoseconds")
    quality: QualityFlag = QualityFlag.GOOD
    source_id: str


class SwitchState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    TRIPPED = "TRIPPED"
    FAULT = "FAULT"


class OperatingState(str, Enum):
    OFF = "OFF"
    STANDBY = "STANDBY"
    RUNNING = "RUNNING"
    FAULT = "FAULT"
    EMERGENCY_STOP = "EMERGENCY_STOP"
```

---

## 3. Equipment Interface Definitions

### 3.1 Battery Interface (`BatteryRackInterface`)

```python
class BatteryRackState(BaseModel):
    rack_id: str
    voltage_v: TelemetryPoint
    current_a: TelemetryPoint
    soc_pct: TelemetryPoint
    soh_pct: TelemetryPoint
    max_cell_temp_c: TelemetryPoint
    min_cell_temp_c: TelemetryPoint
    max_cell_voltage_v: TelemetryPoint
    min_cell_voltage_v: TelemetryPoint
    contactor_state: SwitchState


class BatteryRackInterface:
    def initialize(self, config: dict) -> None: ...
    def step(
        self, current_demand_a: float, ambient_temp_c: float, delta_t_s: float
    ) -> BatteryRackState: ...
    def get_state(self) -> BatteryRackState: ...
```

### 3.2 BMS Interface (`BMSMasterInterface`)

```python
class BMSCommand(BaseModel):
    target_state: OperatingState
    close_contactors_request: bool
    reset_faults_request: bool


class BMSStatus(BaseModel):
    bms_id: str
    operating_state: OperatingState
    charge_current_limit_a: TelemetryPoint
    discharge_current_limit_a: TelemetryPoint
    total_voltage_v: TelemetryPoint
    total_current_a: TelemetryPoint
    active_alarms: list[str]
    active_faults: list[str]


class BMSMasterInterface:
    def process_command(self, cmd: BMSCommand) -> bool: ...
    def evaluate_protection(self, rack_states: list[BatteryRackState]) -> BMSStatus: ...
```

### 3.3 PCS (Inverter) Interface (`PCSInterface`)

```python
class PCSCommand(BaseModel):
    active_power_setpoint_w: float
    reactive_power_setpoint_var: float
    enable_inverter: bool
    reset_fault: bool


class PCSStatus(BaseModel):
    pcs_id: str
    operating_state: OperatingState
    active_power_actual_w: TelemetryPoint
    reactive_power_actual_var: TelemetryPoint
    dc_bus_voltage_v: TelemetryPoint
    ac_voltage_v: TelemetryPoint
    ac_frequency_hz: TelemetryPoint
    efficiency_pct: TelemetryPoint
    igbt_temp_c: TelemetryPoint


class PCSInterface:
    def process_command(self, cmd: PCSCommand) -> bool: ...
    def step(
        self,
        dc_voltage_v: float,
        ac_grid_voltage_v: float,
        ac_grid_freq_hz: float,
        delta_t_s: float,
    ) -> PCSStatus: ...
```

### 3.4 Transformer Interface (`TransformerInterface`)

```python
class TransformerStatus(BaseModel):
    transformer_id: str
    primary_voltage_v: TelemetryPoint
    secondary_voltage_v: TelemetryPoint
    apparent_power_va: TelemetryPoint
    winding_temp_c: TelemetryPoint
    top_oil_temp_c: TelemetryPoint
    tap_position: int


class TransformerInterface:
    def step(
        self,
        primary_power_w: float,
        primary_power_var: float,
        ambient_temp_c: float,
        delta_t_s: float,
    ) -> TransformerStatus: ...
```

### 3.5 Switchgear Interface (`SwitchgearInterface`)

```python
class SwitchgearCommand(BaseModel):
    target_state: SwitchState


class SwitchgearStatus(BaseModel):
    breaker_id: str
    current_state: SwitchState
    interlock_ok: bool
    trip_coil_healthy: bool


class SwitchgearInterface:
    def execute_command(self, cmd: SwitchgearCommand) -> bool: ...
    def get_status(self) -> SwitchgearStatus: ...
```

### 3.6 Auxiliary Systems Interface (`AuxiliaryHVACInterface`)

```python
class HVACStatus(BaseModel):
    hvac_id: str
    cooling_power_w: TelemetryPoint
    power_consumption_w: TelemetryPoint
    fan_speed_pct: TelemetryPoint


class AuxiliaryHVACInterface:
    def step(
        self, target_temp_c: float, current_container_temp_c: float, delta_t_s: float
    ) -> HVACStatus: ...
```

### 3.7 Point of Interconnection (POI) Interface (`POIInterface`)

```python
class POIStatus(BaseModel):
    poi_id: str
    grid_voltage_v: TelemetryPoint
    grid_frequency_hz: TelemetryPoint
    net_active_power_w: TelemetryPoint
    net_reactive_power_var: TelemetryPoint
    power_factor: TelemetryPoint


class POIInterface:
    def step(
        self, total_plant_p_w: float, total_plant_q_var: float, delta_t_s: float
    ) -> POIStatus: ...
```
