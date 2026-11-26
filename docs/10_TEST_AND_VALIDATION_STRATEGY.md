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

**Current state.** The suite is 400 tests, and the enforced coverage policy
(`scripts/check_coverage.py`) sets a per-domain floor of 80 % lines / 60 %
branches globally, with tighter floors on the battery, PCS, controller,
topology and plugin domains. The policy is enforced by the pipeline, not by
convention. `tests/test_illustrative_parameters.py` holds the labelling of
illustrative parameters (`AGENTS.md` §2.14): it asserts that both shipped
example configurations state the `illustrative` marker on the plant and on
every one of their items, that an unstated marker labels rather than stays
silent, that a plant claiming to be validated while one of its items is
illustrative is refused, and that the plant factory carries the marker into
the runtime equipment metadata.

### 2.2 Deterministic Replay & Numerical Stability Verification
- Automated test suites run 100,000 continuous simulation ticks with fixed random seeds.
- Verifies bit-exact output matching against pre-recorded golden telemetry baseline files.
- Checks state variables ($V, I, T, SoC$) for absence of NaN/Inf values or numerical divergence.

### 2.3 Protocol Emulator & Ingress Validation Tests
- Executes mock protocol clients sending valid, out-of-range, stale, and corrupted Modbus/DNP3 payloads.
- Verifies that out-of-range commands are rejected by the Command Validation Boundary without crashing protocol servers.

### 2.4 End-to-End HMI Tests (`Playwright`)
- Automates browser interactions: loading plant scenarios, operating speed controls, toggling switchgear, submitting setpoint overrides, acknowledging alarms, and validating chart renders.

**Current state.** A Playwright project exists (`frontend/playwright.config.ts`, specs in `frontend/e2e/`) and runs in the `Frontend Lint, Test & Build` pipeline job. It drives the **built** HMI in Chromium against a **hermetic mock platform** that answers every `/api/v1/**` request inside the browser, aborts any path it does not model, and blocks every host but the local preview server on `127.0.0.1`. The suite covers the operator path — log in, read the overview, act on the simulation engine behind its confirmation, observe the result, log out — and the safety posture: the session token stays in memory, a backend that is not ready is reported as disconnected, and a refused control action is reported as a failure. The operator path also drives the **wall-clock speed factor** from the screen: the factor in force is displayed, a factor the operator asks for is confirmed by name and dispatched as `SET_SPEED`, and the request travels with the session token. The scenarios listed above that are not yet covered — alarm acknowledgement, chart rendering, switchgear toggling — remain future work.

The frontend also has a **component suite** (`Vitest`, 176 tests in 11 files, 98.02 % line coverage with an enforced 75 % floor) that covers the entry point, the shared components, the login flow, the telemetry hook, the API client and every SCADA view. The two suites are complementary: the component suite proves the HMI's units, the end-to-end suite proves the shipped artefact's operator path.

The component suite also covers the three screens that read the platform rather than asserting on its behalf: the historian query console (the rows the store holds, the empty store, the failed query, the equipment and tag filters and the row limit), the warranty screen (the recorded metrics, the container with no record, the refusal to query without a container identifier, the failed query) and the system-settings screen (the safety invariants the platform reports, the `UNVERIFIED` state when it does not answer, and the refusal to read the platform after the screen is closed).

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
