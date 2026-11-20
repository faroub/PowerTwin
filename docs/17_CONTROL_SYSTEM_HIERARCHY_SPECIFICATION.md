# PowerTwin — Control System Hierarchy Specification (WP05)

## 1. Overview & Architecture Layers

PowerTwin implements a 3-tier hierarchical control architecture designed around clean separation of responsibilities, strict value state distinction, and non-negotiable safety interlocks:

```
+-------------------------------------------------------------------------------+
|                      ENERGY MANAGEMENT SYSTEM (EMS - LAYER C)                 |
|  - Economic Dispatch, Schedule Profiles, Feasibility Validation               |
+-------------------------------------------------------------------------------+
                                       | Requested P, Q Setpoints
                                       v
+-------------------------------------------------------------------------------+
|                      POWER PLANT CONTROLLER (PPC - LAYER B)                   |
|  - POI Regulation, Ramp-Rate Limits, PQ Circle Clamping, PCS Unit Allocation  |
+-------------------------------------------------------------------------------+
                                       | Validated Inverter Commands
                                       v
+-------------------------------------------------------------------------------+
|                   EQUIPMENT CONTROLLER & INTERLOCKS (LAYER A)                 |
|  - Startup/Shutdown Sequencing, Permissive Checks, Watchdog Heartbeat         |
+-------------------------------------------------------------------------------+
                   |                                           |
                   v                                           v
+---------------------------------------+   +-----------------------------------+
|      MASTER BMS CONTROLLER            |   |       PCS INVERTER ACTUATORS      |
+---------------------------------------+   +-----------------------------------+
```

---

## 2. Three Control Layers

### 2.1 Layer A: Equipment Controller (`BESSEquipmentController`)
- Manages local device startup and shutdown sequencing (`STARTING`, `RUNNING`, `STOPPING`, `STANDBY`, `FAULTED`, `EMERGENCY_STOP`).
- Enforces strict startup permissives (HVAC container temperature $< 45^\circ C$, switchgear interlocks OK, BMS contactors closed).
- Monitors communication watchdog heartbeat ($5\text{s}$ timeout limit).

### 2.2 Layer B: Power Plant Controller (`PowerPlantController`)
- Regulates active power ($P$) and reactive power ($Q$) at POI.
- Enforces active power ramp-rate limits ($10\text{ MW/s}$) and plant apparent power capability circle ($P^2 + Q^2 \le S_{\text{plant\_max}}^2$).
- Allocates requested power proportionally among available active PCS units.
- Supports active power vs. reactive power priority modes (`ACTIVE_POWER_PRIORITY` / `REACTIVE_POWER_PRIORITY`).

### 2.3 Layer C: Energy Management System (`EnergyManagementSystem`)
- Executes dispatch schedules, peak shaving, and P-f frequency droop response.
- **Feasibility Verification**: The EMS **NEVER** assumes a requested dispatch is feasible. It runs `check_feasibility()` verifying stored energy, SoC limits ($5\% - 95\%$), BMS limits, and equipment availability before dispatching.

---

## 3. Five Explicit Value Distinctions

1. **Requested Setpoints**: Desired target from EMS or HMI Operator.
2. **Accepted Setpoints**: Validated setpoint accepted by PPC after applying plant limits.
3. **Equipment Commands**: Actuation signals sent to individual PCS / BMS units.
4. **Actual Equipment Outputs**: Physical state produced by PCS/Battery dynamics.
5. **POI Measurements**: Telemetry values reported by POI meter.

---

## 4. Traceable Control-Command Audit Logging

All control actions, state transitions, setpoint requests, and rejection decisions are logged in an immutable audit structure (`ControlCommandLog`) capturing:
- `timestamp_ns`: Nanosecond simulation clock
- `source_layer`: `EMS`, `PPC`, `EQUIPMENT_CONTROLLER`, `OPERATOR`
- `target_component`: Target ID e.g. `PCS_01`, `BMS_MASTER`
- `action_name`: Action identifier
- `requested_value` vs `accepted_value`
- `status`: `ACCEPTED`, `REJECTED_INFEASIBLE`, `REJECTED_INTERLOCK`, `DERATED`, `FAULT_TRIP`
