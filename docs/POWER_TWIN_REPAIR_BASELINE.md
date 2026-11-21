# PowerTwin — Independent Baseline and Defect Reproduction Report

## 1. Executive Summary

This report establishes the independent baseline and defect reproduction analysis for the **PowerTwin Modular Industrial BESS Simulator & Emulator Platform**. 

All findings were verified against the checked-out repository state. Each item has been analyzed for root cause, affected files and classes, fix dependencies, ineffective existing tests, preserved functionality, proposed implementation prompts, and acceptance tests.

---

## 2. Confirmed Defects vs. Risks and Design Limitations

### Summary Classification Table

| ID | Domain | Classification | Description | Severity |
| :--- | :--- | :--- | :--- | :--- |
| **PT-001** | GitHub Actions | Confirmed Defect | Hardcoded backend coverage percentage (`percentage=90`) in CI workflow step output | Medium |
| **PT-002** | Security CI | Confirmed Defect | Security audit job suppresses failures via `|| true` on `pip-audit` and `npm audit` | High |
| **PT-003** | Release | Design Limitation | Non-standard placeholder SBOM JSON generation instead of using standard tools (`syft`/`cyclonedx`) | Low |
| **PT-004** | API Security | Confirmed Defect | `/api/v1/simulation/control` POST endpoint lacks RBAC user token authentication | High |
| **PT-005** | Engine | Confirmed Defect | `SimulationTask` state serialization omits domain variables (SoC, voltage, current) during snapshot restore | High |
| **PT-006** | Topology | Confirmed Defect | `PlantTopologyFactory.build_plant()` instantiates duplicate unlinked battery and PCS instances | Critical |
| **PT-007** | Battery Model | Confirmed Defect | `get_available_power_limits()` divides energy capacity headroom by $1\text{ h}$ implicitly, clamping C-rate power | Critical |
| **PT-008** | PCS Model | Confirmed Defect | Inverter ramp limiter divides charging power by efficiency, polluting ramp state | High |
| **PT-009** | EMS Controller | Confirmed Defect | EMS feasibility check evaluates a single battery container (`battery_systems[0]`) instead of plant total | Critical |
| **PT-010** | Plugins | Confirmed Defect | `PluginRegistry._active_plugins` map keyed by `plugin_id` causes overwrites on multi-instance equipment | High |
| **PT-011** | CIL Gateway | Confirmed Defect | `ProtocolGatewayService` records Modbus writes to registers but does not forward values to PPC/EMS dispatch | High |
| **PT-012** | Historian | Confirmed Defect | `flush_buffer_to_db()` pops queue items before DB transaction commit, risking data loss on DB failure | High |
| **PT-013** | Web HMI | Confirmed Defect | `/api/v1/overview` endpoint returns hardcoded static numbers instead of reading live simulation telemetry | Medium |

---

## 3. Detailed Defect Analysis & Reproduction

### PT-001: Hardcoded Backend Coverage Reporting in CI Output
- **File Involved**: [.github/workflows/reusable-backend.yml](file:///home/faroub/Documents/Projects/PowerTwin/.github/workflows/reusable-backend.yml) (`jobs.backend-test.steps.cov`)
- **Root Cause**: The step extracts coverage by echoing `echo "percentage=90" >> $GITHUB_OUTPUT` regardless of actual `coverage.xml` content.
- **Impact**: Coverage drops are masked in GitHub Action job outputs.
- **Fix Dependency**: None.
- **Preserved Functionality**: XML coverage artifact upload.

### PT-002: Security Audit False Positive Suppression
- **File Involved**: [.github/workflows/security.yml](file:///home/faroub/Documents/Projects/PowerTwin/.github/workflows/security.yml) (`jobs.dependency-audit`)
- **Root Cause**: Commands use `pip-audit ... || true` and `npm audit ... || true`, causing the workflow step to return exit code 0 even when critical vulnerabilities exist.
- **Impact**: Vulnerable dependencies pass security gates silently.
- **Fix Dependency**: None.

### PT-003: Non-Standard Placeholder SBOM Generation
- **File Involved**: [.github/workflows/release.yml](file:///home/faroub/Documents/Projects/PowerTwin/.github/workflows/release.yml) (`jobs.release-build`)
- **Root Cause**: Uses `echo '{"name": "PowerTwin"...}' > sbom.json` instead of a standardized SBOM generator.
- **Classification**: Design Limitation / Low Risk.

### PT-004: Missing RBAC Authentication Middleware on Simulation Control API
- **Files Involved**: [backend/app/api/v1/simulation_ctrl.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/api/v1/simulation_ctrl.py) (`dispatch_simulation_control`), [backend/app/core/rbac.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/core/rbac.py)
- **Root Cause**: Route handler accepts POST requests without checking `UserSession` or `Permission.MODIFY_SIMULATION`.
- **Impact**: Unauthorized REST requests can trigger simulation pause/reset.
- **Fix Dependency**: PT-013 (HMI API wiring).

### PT-005: Incomplete Domain Task State Serialization in Simulation Snapshot
- **Files Involved**: [backend/app/simulation/task.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/simulation/task.py) (`SimulationTask.get_task_state`, `set_task_state`), [plugins/generic_battery.py](file:///home/faroub/Documents/Projects/PowerTwin/plugins/generic_battery.py), [plugins/generic_pcs.py](file:///home/faroub/Documents/Projects/PowerTwin/plugins/generic_pcs.py)
- **Root Cause**: `get_task_state()` only serializes execution counts and enabled flags, omitting domain variables (`soc_pct`, `voltage_v`, `current_a`, `igbt_temp_c`).
- **Impact**: Restoring a snapshot resets engine time but leaves physical variables un-restored.
- **Fix Dependency**: PT-006 (Equipment Instance Linking).

### PT-006: Duplicate Unlinked Battery and PCS Instance Creation in Topology Factory
- **Files Involved**: [backend/app/topology/factory.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/topology/factory.py) (`PlantTopologyFactory.build_plant`)
- **Root Cause**: Instantiates `GenericBatterySystemModel` into `battery_systems` list and separately creates `GenericBatteryPlugin` task instances. The two instances are not linked or shared.
- **Impact**: Simulation scheduler steps the task instance while EMS/PPC queries the unstepped model instance.
- **Fix Dependency**: Crucial prerequisite for PT-005, PT-007, PT-009.

### PT-007: Implicit 1-Hour Time Window Clamping in Available Power Limits
- **Files Involved**: [backend/app/models/battery/system.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/models/battery/system.py) (`GenericBatterySystemModel.get_available_power_limits`)
- **Root Cause**: Calculates `max_ch_power_from_energy = headroom_energy_wh / self.config.charge_efficiency` assuming a 1-hour discharge/charge window ($1\text{ h}$).
- **Impact**: Clamps high C-rate instantaneous power on multi-MW battery containers during short simulation ticks.
- **Fix Dependency**: PT-006.

### PT-008: Conflation of AC Terminal Power and Efficiency-Adjusted DC Power in Inverter Ramp Limiter
- **Files Involved**: [backend/app/models/pcs/pcs_model.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/models/pcs/pcs_model.py) (`GenericPCSModel.step`)
- **Root Cause**: During charging, `self.actual_p_w = p_actual_next / efficiency`. On the subsequent tick, `p_delta = accepted_p - actual_p` subtracts the efficiency-adjusted DC power from AC setpoint.
- **Impact**: Creates ramp limiter inaccuracy during charging cycles.
- **Fix Dependency**: None.

### PT-009: Single-Battery Power Limit Evaluation in EMS Dispatch Feasibility Check
- **Files Involved**: [backend/app/controllers/ems.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/controllers/ems.py) (`EnergyManagementSystem.check_feasibility`)
- **Root Cause**: Evaluates `battery.get_available_power_limits()` on a single `battery: GenericBatterySystemModel` parameter instead of summing available power across all active containers in `plant.battery_systems`.
- **Impact**: Plant discharge capability is artifically capped at Container 01's capacity on multi-container plants.
- **Fix Dependency**: PT-006, PT-007.

### PT-010: Key Collision on Plugin ID in Active Plugins Map for Multi-Instance Equipment
- **Files Involved**: [plugins/registry.py](file:///home/faroub/Documents/Projects/PowerTwin/plugins/registry.py) (`PluginRegistry.create_and_initialize`, `enable_plugin`)
- **Root Cause**: `self._active_plugins[plugin_id] = plugin` uses static `plugin_id` (e.g. `'generic_battery_v1'`) as dictionary key instead of instance name/equipment_id (e.g. `'CONTAINER_01'`).
- **Impact**: Instantiating multiple containers overwrites earlier instances in `_active_plugins`.
- **Fix Dependency**: None.

### PT-011: Unlinked Modbus CIL Command Register to Plant Controller Dispatch Loop
- **Files Involved**: [backend/app/communication/gateway_service.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/communication/gateway_service.py) (`ProtocolGatewayService.process_external_command`)
- **Root Cause**: External Modbus writes update `modbus_server.register_values[address]` and log entries, but the setpoints are never forwarded to `plant.ems.dispatch_step()` or `plant.ppc`.
- **Impact**: CIL controller setpoints written over Modbus do not affect plant simulation physics.
- **Fix Dependency**: PT-009.

### PT-012: Popped Buffer Data Loss on Database Flush Transaction Failure
- **Files Involved**: [backend/app/historian/service.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/historian/service.py) (`HistorianService.flush_buffer_to_db`)
- **Root Cause**: Pops items from queue via `get_nowait()` before `session.commit()`. If DB commit fails, popped items are lost.
- **Impact**: Violates zero data loss policy if DB connection drops mid-flush.
- **Fix Dependency**: None.

### PT-013: Hardcoded Static Telemetry in HMI Overview API Endpoint
- **Files Involved**: [backend/app/api/v1/overview.py](file:///home/faroub/Documents/Projects/PowerTwin/backend/app/api/v1/overview.py) (`get_plant_overview`)
- **Root Cause**: Returns fixed static dict (`4.85 MW`, `64.5% SoC`) instead of querying active `BuiltPlantInstance`.
- **Impact**: HMI Overview dashboard does not reflect live simulation state transitions.
- **Fix Dependency**: PT-006, PT-009.

---

## 4. Fix Dependencies & Recommended Implementation Sequence

```
+-------------------------------------------------------------------------------+
| PHASE 1: Core Physics, Topology & Model Fixes                                 |
| - PT-006: Equipment Instance Ownership in Topology Factory                    |
| - PT-007: Battery C-Rate Power Limits Calculation                             |
| - PT-008: PCS Ramp Limiter AC/DC Power Separation                             |
| - PT-009: Multi-Container EMS Feasibility Aggregation                         |
| - PT-010: Plugin Registry Active Instance Keying                             |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| PHASE 2: Engine Snapshots, CIL & Integration Wiring                           |
| - PT-005: Task Domain State Serialization in Snapshots                        |
| - PT-011: CIL Modbus Command Wiring to Plant Dispatch                        |
| - PT-012: Historian Buffer Transaction Rollback Protection                    |
| - PT-013: Live Plant Telemetry Wiring in HMI Overview Endpoint               |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| PHASE 3: Security, API RBAC & CI/CD Pipeline Hardening                        |
| - PT-001: Dynamic Coverage Reporting in CI Workflow                           |
| - PT-002: Security Audit Failure Enforcement in CI                            |
| - PT-004: RBAC Session Authentication on Control API Endpoints                |
| - PT-003: Standardized SBOM Generation                                        |
+-------------------------------------------------------------------------------+
```

---

## 5. Ineffective Existing Tests

The following existing tests pass under current code but fail to verify underlying physical/logical defects:

1. `tests/test_plant_topology.py::test_reference_10mw_20mwh_plant_topology_loading`:
   - Passes because it checks list lengths (`len(battery_systems) == 4`), but fails to detect that `battery_systems[0]` and `simulation_engine.scheduler._tasks["CONTAINER_01"]` are separate unlinked objects (**PT-006**).
2. `tests/test_control_architecture.py::test_ems_dispatch_infeasibility_when_battery_empty`:
   - Passes because it tests a single battery instance, masking the defect where EMS ignores Containers 02, 03, 04 on multi-container plants (**PT-009**).
3. `tests/test_protocol_gateway.py::test_watchdog_heartbeat_timeout_handling`:
   - Passes because it checks Modbus register values in memory, masking the defect where register writes do not dispatch commands to the plant simulator (**PT-011**).
4. `tests/test_hmi_workflows.py::test_hmi_overview_endpoint`:
   - Passes because it asserts `data["active_power_mw"] == 4.85`, which hardcodes the static mock value without testing if live simulation changes update the HMI (**PT-013**).

---

## 6. Preserved Functionality

During the repair phase, the following core features **MUST BE PRESERVED**:
- **Non-Negotiable Safety Invariants**: `SIMULATION_ONLY = True`, `HARDWARE_INTEGRATION_ENABLED = False`, `ALLOW_EXTERNAL_MODBUS_WRITES = False` (default), Loopback Host Binding `127.0.0.1`.
- **Sign Conventions**: $+P$ = Discharging / Exporting to grid; $-P$ = Charging / Importing from grid; $+Q$ = Supplying VARs.
- **Deterministic Replay**: 100% reproducible execution using integer nanosecond tick clock and seeded RNG (`seed=42`).
- **Zero Silent Data Loss Historian**: Emergency disk overflow fallback when memory buffer fills.

---

## 7. Prioritized Repair Backlog (PT-001 to PT-013)

### PT-001: Dynamic Coverage Reporting in CI Workflow
- **Prompt**: "Update .github/workflows/reusable-backend.yml to parse coverage.xml dynamically rather than echoing hardcoded percentage=90."
- **Acceptance Test**: Verify CI output reflects true coverage extracted from `coverage.xml`.

### PT-002: Security Audit Failure Enforcement in CI
- **Prompt**: "Remove '|| true' suppression from pip-audit and npm-audit steps in .github/workflows/security.yml."
- **Acceptance Test**: Verify security workflow fails if high-severity vulnerabilities exist.

### PT-003: Standardized SBOM Generation
- **Prompt**: "Update .github/workflows/release.yml to generate standard SBOM files using syft or cyclonedx-cli."
- **Acceptance Test**: Verify valid SBOM JSON artifact is produced during release build.

### PT-004: RBAC Session Authentication on Control API Endpoints
- **Prompt**: "Attach UserSession dependency and Permission.MODIFY_SIMULATION check to /api/v1/simulation/control route handler."
- **Acceptance Test**: Verify POST request without valid session token returns HTTP 401/403.

### PT-005: Task Domain State Serialization in Snapshots
- **Prompt**: "Update SimulationTask.get_task_state() and set_task_state() (and plugin subclasses) to serialize domain variables (soc_pct, voltage_v, current_a, igbt_temp_c)."
- **Acceptance Test**: Create snapshot mid-simulation, modify state, restore snapshot, assert physical variables match exact snapshot state.

### PT-006: Equipment Instance Ownership in Topology Factory
- **Prompt**: "Refactor PlantTopologyFactory.build_plant() so that Equipment Plugin tasks directly wrap and own the physical equipment model instances rather than creating unlinked duplicate models."
- **Acceptance Test**: Assert `plant.battery_systems[0]` and `simulation_engine.scheduler._tasks["CONTAINER_01"].physical_model` refer to the exact same object.

### PT-007: Battery C-Rate Power Limits Calculation
- **Prompt**: "Update GenericBatterySystemModel.get_available_power_limits() to calculate power headroom based on rated C-rate power capacity without implicit 1-hour window clamping."
- **Acceptance Test**: Verify a 5 MWh container at 50% SoC returns available discharge power equal to its rated C-rate capacity.

### PT-008: PCS Ramp Limiter AC/DC Power Separation
- **Prompt**: "Refactor GenericPCSModel.step() so that active power ramp rate limiting operates strictly on AC terminal power before efficiency losses are applied."
- **Acceptance Test**: Verify charging ramp rate matches expected AC ramp limit linearly over step transitions.

### PT-009: Multi-Container EMS Feasibility Aggregation
- **Prompt**: "Update EnergyManagementSystem.check_feasibility() to accept a list[GenericBatterySystemModel] and sum charge/discharge power limits across all active, available containers."
- **Acceptance Test**: On a 4-container plant, verify EMS feasibility check returns 4x single-container capacity.

### PT-010: Plugin Registry Active Instance Keying
- **Prompt**: "Update PluginRegistry._active_plugins dictionary to key active plugin instances by instance name/equipment_id rather than plugin_id."
- **Acceptance Test**: Instantiate 4 containers of type 'generic_battery_v1' and verify all 4 instances exist in `_active_plugins`.

### PT-011: CIL Modbus Command Wiring to Plant Dispatch
- **Prompt**: "Wire ProtocolGatewayService.process_external_command() to forward accepted active/reactive setpoints directly to plant EMS/PPC dispatch loop."
- **Acceptance Test**: Send Modbus write to register 100 (+5 MW) and verify plant POI meter measures +5 MW export.

### PT-012: Historian Buffer Transaction Rollback Protection
- **Prompt**: "Update HistorianService.flush_buffer_to_db() to retain items in temporary batch and re-queue or disk-overflow them if database commit fails."
- **Acceptance Test**: Simulate DB commit error during flush; verify popped items are preserved in memory queue or overflow file.

### PT-013: Live Plant Telemetry Wiring in HMI Overview Endpoint
- **Prompt**: "Update /api/v1/overview endpoint in backend/app/api/v1/overview.py to read live telemetry from the active BuiltPlantInstance."
- **Acceptance Test**: Change simulation state or dispatch setpoint; verify `/api/v1/overview` reflects updated active power and SoC.

---

## 8. Engineering Approval Decisions

The following architectural decisions require engineering review prior to implementation:

1. **PPC Unit Allocation Strategy**: Confirm whether PPC should use equal proportional allocation or efficiency-optimized merit-order dispatch among active PCS units.
2. **CIL Command Timeout Action**: Confirm whether stale Modbus commands (> 5s without heartbeat) should trigger a graceful PPC derate or immediate Layer A contactor trip.
3. **Snapshot Version Compatibility Policy**: Confirm whether minor SemVer snapshot schema changes should support automatic migration or require strict exact-version matching.
