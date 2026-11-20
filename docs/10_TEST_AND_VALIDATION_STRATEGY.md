# PowerTwin — Test and Validation Strategy

## 1. Overview & Testing Levels

PowerTwin enforces a comprehensive testing strategy combining unit tests, integration tests, deterministic replay validation, and end-to-end HMI testing.

```
+-------------------------------------------------------------------------------+
|                       PLAYWRIGHT END-TO-END HMI TESTS                         |
|  - UI Workflows, Confirmation Modals, WebSocket Streaming, Charting           |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
|                      INTEGRATION & CIL EMULATOR TESTS                         |
|  - Multi-Component DAG Ticks, Modbus/DNP3 Server Register Reads/Writes, DB    |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
|                          PYTEST UNIT TESTS & REPLAY                           |
|  - Cell Math, Inverter Curves, Protection Limiters, Deterministic Bit-Exact    |
+-------------------------------------------------------------------------------+
```

---

## 2. Testing Methodologies

### 2.1 Backend Unit Tests (`pytest`)
- Focuses on individual model equations, equivalent circuit calculations, Pydantic configuration schemas, and controller state machines.
- Target: $>85\%$ line coverage across all backend modules.

### 2.2 Deterministic Replay & Numerical Stability Verification
- Automated test suites run 100,000 continuous simulation ticks with fixed random seeds.
- Verifies bit-exact output matching against pre-recorded golden telemetry baseline files.
- Checks state variables ($V, I, T, SoC$) for absence of NaN/Inf values or numerical divergence.

### 2.3 Protocol Emulator & Ingress Validation Tests
- Executes mock protocol clients sending valid, out-of-range, stale, and corrupted Modbus/DNP3 payloads.
- Verifies that out-of-range commands are rejected by the Command Validation Boundary without crashing protocol servers.

### 2.4 End-to-End HMI Tests (`Playwright`)
- Automates browser interactions: loading plant scenarios, operating speed controls, toggling switchgear, submitting setpoint overrides, acknowledging alarms, and validating chart renders.

---

## 3. Requirement Traceability Matrix

| Requirement ID | Requirement Description | Implementation Module Path | Verification Test Suite |
| :--- | :--- | :--- | :--- |
| **SR-001** | Simulation Only default mode | `backend/config/settings.py` | `tests/unit/test_config.py::test_default_simulation_mode` |
| **SR-002** | Hardware interface prohibition | `backend/core/safety.py` | `tests/unit/test_safety.py::test_hardware_flag_check` |
| **SR-006** | Protection interlock precedence | `backend/controllers/bms.py` | `tests/unit/test_bms_protection.py` |
| **SR-008** | Ingress command validation | `backend/api/validation.py` | `tests/integration/test_command_validation.py` |
| **SR-010** | Immutable audit log write | `backend/db/audit.py` | `tests/integration/test_audit_logging.py` |
| **FR-EQP-001**| Multi-tier battery topology | `backend/models/battery/` | `tests/unit/test_battery_topology.py` |
| **FR-EQP-005**| PCS efficiency & PQ curves | `backend/models/pcs/` | `tests/unit/test_pcs_efficiency.py` |
| **FR-CTL-004**| Frequency droop control | `backend/controllers/ppc.py` | `tests/unit/test_frequency_droop.py` |
| **FR-ENG-001**| Deterministic tick clock | `backend/engine/clock.py` | `tests/unit/test_sim_clock.py` |
| **FR-ENG-003**| Bit-exact scenario replay | `backend/engine/replay.py` | `tests/integration/test_replay_determinism.py` |
| **FR-DAT-001**| TimescaleDB telemetry write | `backend/db/historian.py` | `tests/integration/test_timescale_ingest.py` |
| **FR-PLG-001**| Vendor plugin loading | `plugins/manager.py` | `tests/unit/test_plugin_manager.py` |
| **NFR-PERF-001**| 100 Hz simulation performance| `backend/engine/runner.py` | `tests/performance/test_tick_performance.py` |
| **NFR-SECU-001**| RBAC & JWT auth on API | `backend/api/auth.py` | `tests/e2e/test_auth_security.py` |
