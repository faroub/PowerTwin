# PowerTwin — Development Roadmap

## 1. Overview

The PowerTwin development roadmap spans five phased releases, prioritizing core simulation determinism, safety boundaries, and control logic before expanding into external CIL protocols and advanced digital twin calibration.

---

## 2. Phase Breakdown & Deliverables

```
+-------------------------------------------------------------------------------+
| PHASE 1: Core Physics, Standard Interfaces & Simulation Clock                 |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| PHASE 2: Control System Hierarchy, TimescaleDB Historian & Web HMI            |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| PHASE 3: Vendor Plugin Architecture & Protocol Emulators (CIL Mode)           |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| PHASE 4: Advanced Scenarios, Degradation Models & Digital Twin Calibration    |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| PHASE 5: Controlled Hardware-in-the-Loop (HIL) (Future Phase)                 |
+-------------------------------------------------------------------------------+
```

### Phase 1: Core Engine, Basic Physics & Standardized Interfaces
- **Milestone 1.1**: Central tick-driven simulation clock, execution DAG engine, and state snapshot serializer.
- **Milestone 1.2**: Core equivalent circuit battery models (cell/rack/container electro-thermal equations).
- **Milestone 1.3**: Simplified PCS inverter model, transformer, switchgear, and POI models.
- **Milestone 1.4**: Unit tests and deterministic replay verification framework.

### Phase 2: Control Hierarchy, Database Historian & Web HMI
- **Milestone 2.1**: Master BMS protection state machine, PPC frequency droop/Volt-VAR algorithms, and basic EMS schedule runner.
- **Milestone 2.2**: PostgreSQL + TimescaleDB schema migration, telemetry hypertable ingest, and audit logging.
- **Milestone 2.3**: FastAPI REST and WebSocket telemetry streaming endpoints.
- **Milestone 2.4**: React + TypeScript HMI with Overview Dashboard, Interactive SLD, Command Panel, and Charting.

### Phase 3: Vendor Plugin System & Industrial Protocol Emulators (CIL)
- **Milestone 3.1**: Plugin manager, metadata validation, manifest verification, and execution sandbox.
- **Milestone 3.2**: Modbus TCP/RTU server emulator with address mapping and ingress validation boundary.
- **Milestone 3.3**: DNP3 Outstation and SunSpec Modbus model implementations.
- **Milestone 3.4**: CIL integration tests with external software controller simulators.

### Phase 4: Advanced Scenarios, Degradation Models & Calibration
- **Milestone 4.1**: Multi-year battery capacity fade (SEI layer) and power fade degradation models.
- **Milestone 4.2**: Synthetic grid fault scenario runner (voltage sags, frequency steps, islanding events).
- **Milestone 4.3**: Digital twin parameter fitting and warranty analysis tools.

### Phase 5: Controlled Hardware-in-the-Loop (HIL) Integration (Future Phase)
- **Prerequisite**: Independent safety audit sign-off and explicit hardware integration authorization.
- **Milestone 5.1**: Hardware I/O driver abstraction layer.
- **Milestone 5.2**: Physical amplifier and real BMS microcontroller testbed validation.
