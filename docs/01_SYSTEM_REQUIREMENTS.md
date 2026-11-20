# PowerTwin — System Requirements Specification

## 1. Overview

This document specifies the functional, non-functional, safety, and unverifiable requirements for the PowerTwin BESS simulator and emulator platform. All requirements carry unique identifiers for end-to-end traceability across module implementations, configuration files, and test suites.

---

## 2. Safety Requirements & Non-Negotiable Rules (SR)

| Requirement ID | Description | Enforcement Mechanism |
| :--- | :--- | :--- |
| **SR-001** | Default application operational mode MUST be **SIMULATION ONLY**. | Hardcoded configuration default; zero network sockets open to external hardware upon boot. |
| **SR-002** | No core code or plugin may automatically discover, scan, connect to, command, or write to real industrial equipment. | Explicit hardware enablement flag (`hardware_mode_enabled = False`) required in verified config file. |
| **SR-003** | Default routes, network interfaces, protocol addresses, credentials, or IP configurations MUST NOT target physical field networks or devices. | Strict validation of binding IP addresses (bind to `127.0.0.1` or isolated container network only). |
| **SR-004** | All external hardware and protocol server interfaces MUST be disabled by default and require explicit operator enablement. | Opt-in execution flag with administrative audit log entry required prior to binding protocol listeners. |
| **SR-005** | Simulated devices, external controller interfaces, and physical hardware driver connections MUST be strictly segregated in code and UI. | Explicit type system separation (`SimulatedDevice`, `EmulatedControllerInterface`, `PhysicalHardwareInterface`). |
| **SR-006** | Simulation models MUST NOT bypass, disable, override, or weaken BMS/PCS safety interlocks, watchdogs, or Emergency Stop (E-Stop) logic. | Protection logic evaluated prior to dispatch command execution in every tick loop. |
| **SR-007** | Software protection routines MUST NOT be claimed as an unvalidated substitute for certified physical hardware protection devices. | System documentation and HMI banners explicitly designate software protection as non-certified simulation logic. |
| **SR-008** | Inbound control commands MUST be rejected if they are out-of-range, stale, contradictory, corrupted, or incorrectly timestamped. | Strict schema and range validation boundary at API/Protocol input layers. |
| **SR-009** | Safe command limits and rate-of-change limiters (ramp rates) MUST be applied at every controller and equipment boundary. | Pydantic model validation and stateful command rate limiter wrappers. |
| **SR-010** | All incoming commands, setpoint alterations, configuration edits, fault triggers, and operator interventions MUST be logged in an immutable audit trail. | Audit logger with cryptographic sequence hashing and persistent database write. |
| **SR-011** | Automatic silent fallback between real physical connections and simulated components (or vice-versa) is STRICTLY PROHIBITED. | Hard crash / explicit fault state raised immediately upon connection loss or transition attempt. |
| **SR-012** | Writable control interfaces MUST NOT be exposed to unauthenticated or untrusted networks. | Mandatory TLS 1.3, RBAC authentication, and local network binding checks. |
| **SR-013** | Manufacturer equipment specifications and models MUST NOT be claimed as authoritative unless validated against official factory test data. | Disclaimer tagging (`data_source: "ILLUSTRATIVE"`) enforced across unvalidated model configs. |
| **SR-014** | All default, demo, or template equipment parameters MUST be explicitly labeled as `ILLUSTRATIVE`. | Parameter metadata schema requires `is_illustrative: bool = True` unless factory dataset attached. |

---

## 3. Functional Requirements (FR)

### 3.1 Equipment Modeling (FR-EQP)
- **FR-EQP-001**: System shall model multi-tier battery topology (Cell -> Module -> Rack -> Container -> Plant).
- **FR-EQP-002**: System shall model non-linear open-circuit voltage (OCV) curves as a function of SoC and temperature.
- **FR-EQP-003**: System shall calculate internal resistance ($R_{0}$, $R_{ct}$, $C_{dl}$) dynamics for charge and discharge states.
- **FR-EQP-004**: System shall compute lumped thermal energy balance per rack/container including Joule heating ($I^2 R$) and HVAC heat extraction.
- **FR-EQP-005**: System shall model PCS inverter efficiency curves, active power ($P$) limit, reactive power ($Q$) capability curves (PQ-diagram limits), and thermal derating.
- **FR-EQP-006**: System shall model step-up transformer impedance, core losses, copper losses, and tap ratio.
- **FR-EQP-007**: System shall model MV switchgear circuit breaker state transitions (Open, Closed, Tripped, Fault).
- **FR-EQP-008**: System shall model auxiliary loads (HVAC, fire suppression, control electronics power draw).
- **FR-EQP-009**: System shall simulate Point of Interconnection (POI) voltage, frequency, power flow, and net meter values.

### 3.2 Control Systems & EMS (FR-CTL)
- **FR-CTL-001**: System shall support Battery Management System (BMS) Rack/Master state machines (Init, Standby, Ready, Charging, Discharging, Fault, E-Stop).
- **FR-CTL-002**: System shall provide active/passive cell balancing simulation models.
- **FR-CTL-003**: System shall provide Power Plant Controller (PPC) active power regulation, reactive power control (Volt-VAR, fixed PF), and ramp rate limiting.
- **FR-CTL-004**: System shall support primary frequency response (Frequency-Power / P-f droop control and Fast Frequency Response).
- **FR-CTL-005**: System shall execute Energy Management System (EMS) operational modes (Peak Shaving, Self-Consumption, Arbitrage Dispatch, Scheduled Profile).

### 3.3 Simulation Engine (FR-ENG)
- **FR-ENG-001**: Engine shall use deterministic integer tick timing (microseconds or milliseconds) as the central simulation time reference.
- **FR-ENG-002**: Engine shall support Pause, Resume, Single-Step, Reset, and Speed Factor (0.1x to 100x wall-clock) execution modes.
- **FR-ENG-003**: Engine shall support deterministic scenario replay given an identical initial configuration state and random seed.
- **FR-ENG-004**: Engine shall resolve execution ordering using a directed acyclic graph (DAG) of model dependencies per simulation tick.

### 3.4 Data & Communication (FR-DAT)
- **FR-DAT-001**: System shall record telemetry measurements to a time-series database (TimescaleDB) with microsecond timestamp precision.
- **FR-DAT-002**: System shall attach `timestamp`, `quality_flag` (Good, Bad, Uncertain), and `source_id` to every measurement and command.
- **FR-DAT-003**: System shall provide Modbus TCP/RTU, DNP3, and SunSpec communication server emulators for external CIL integration.
- **FR-DAT-004**: System shall expose a REST and WebSocket API via FastAPI for HMI status updates and control interaction.

### 3.5 Vendor Plugins (FR-PLG)
- **FR-PLG-001**: System shall load vendor equipment models and custom controllers using a standardized plugin interface.
- **FR-PLG-002**: System shall validate plugin metadata, capability manifest, and configuration compatibility prior to initialization.

---

## 4. Non-Functional Requirements (NFR)

- **NFR-PERF-001**: The simulation engine shall process a 100 MW / 400 MWh BESS plant model (50 racks, 10 PCS units) at 100 Hz simulation rate using $<50\%$ CPU usage on a standard 8-core host.
- **NFR-PERF-002**: HMI real-time dashboard telemetry updates shall maintain a latency of $<200\text{ ms}$ from simulation tick execution to UI render.
- **NFR-RELI-001**: The simulation engine shall achieve deterministic replay reproducibility across 1,000,000 ticks with zero state divergence.
- **NFR-SECU-001**: All REST and WebSocket endpoints shall require token authentication (JWT/API Key) and role-based access control (RBAC).
- **NFR-MAINT-001**: Codebase shall achieve $>85\%$ unit test line coverage across generic core models and control logic.

---

## 5. Unverifiable Requirements at Initial Phase (UNV)

The following requirements are identified for future phases and cannot be verified during initial simulation-only implementation:

| Requirement ID | Description | Reason for Unverifiability in Initial Phase |
| :--- | :--- | :--- |
| **UNV-001** | Sub-millisecond hard real-time latency for physical HIL amplifiers. | Standard desktop OS (Linux/Windows) lacks hard real-time kernel patches (RT-PREEMPT) and physical DAQ hardware in initial phase. |
| **UNV-002** | Manufacturer-exact cell thermal degradation accuracy under 10-year cycling. | Requires multi-year physical chamber test datasets from specific cell manufacturers not available in early open development. |
| **UNV-003** | Physical grid-code compliance certification (e.g. IEEE 1547 / UL 1741 SA physical hardware test suite). | Requires certified physical grid simulator hardware lab testbed. |
