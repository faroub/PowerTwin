# PowerTwin — Platform Known Limitations & Engineering Disclaimers

This document is the authoritative register of what PowerTwin does **not** do,
what it does only approximately, and what it has deliberately left unimplemented.
Every limitation below is stated together with its practical consequence, so
that no reader has to infer an impact from a heading.

---

## 1. Explicit Safety and Certification Disclaimer

> [!CAUTION]
> **SIMULATION & CIL EMULATION DISCLAIMER**:
> PowerTwin is a software simulation, emulation, and Controller-in-the-Loop (CIL) testing platform.
> It is **NOT** certified battery safety protection hardware, a physical inverter, or a replacement for real BESS equipment.
> Direct connection of this software to physical high-voltage BESS contactors or live industrial power networks without formal physical laboratory authorization is strictly prohibited.

The application runs in `SIMULATION_ONLY` mode. `HARDWARE_INTEGRATION_ENABLED`
and `AUTOMATIC_DEVICE_DISCOVERY_ENABLED` are compile-time constants set to
`False` and are never read from configuration, so no configuration file, API
request or environment variable can enable them. The only network listener that
accepts commands is the CIL protocol gateway, which is bound to loopback and
which refuses to accept writes on a non-loopback interface.

No model in this platform has been validated against a manufacturer's certified
test data. **No manufacturer-accuracy claim is made for any model**, and the
vendor plugins are derived from publicly available datasheet specifications.

---

## 2. Technical & Physical Model Limitations

### 2.1 Simulation Engine & Time Resolution

- **Fixed Step Frequency**: The simulation engine operates on a fixed integer nanosecond tick clock with a default step size of $10\text{ ms}$ ($100\text{ Hz}$ execution frequency).
- **Phasor-Domain Scope**: Sub-millisecond electromagnetic transient (EMT) phenomena, high-frequency PWM switching harmonics ($> 1\text{ kHz}$), and sub-microsecond lightning surge events are beyond the scope of $100\text{ Hz}$ phasor-domain simulation.
- **No Hard Real-Time Guarantee**: All throughput figures were measured on an ordinary desktop operating system. The platform must not be relied upon for hard real-time behaviour on a general-purpose OS.

### 2.2 Battery & BMS Physical Models

- **Equivalent Circuit Formulation**: Battery cell dynamics utilize an energy-balanced Equivalent Circuit Model (ECM) with open-circuit voltage (OCV) vs. SoC interpolation and internal resistance ($R_{\text{int}}$) losses.
- **Lumped Thermal Mass**: Thermal dynamics assume a lumped container heat capacity ($J/\text{^\circ C}$) with convective cooling. Spatial 3D cell-to-cell thermal gradients and CFD coolant fluid dynamics are not computed.
- **BMS Protection Logic**: The master BMS model simulates protection threshold logic for control loop testing. It does not replace certified hardware BMS microcontrollers or hardwired analog safety relays.
- **No Ageing Model**: Calendar ageing, cycle-induced capacity fade and calendar-time-dependent internal resistance growth are **NOT IMPLEMENTED**. The usable capacity is a fixed configuration value.

### 2.3 PCS Inverter Models

- **Capability Circle & Ramp Limiter Scope**: Inverters model steady-state $P/Q$ capability circle clamping ($P^2 + Q^2 \le S_{\text{max, eff}}^2$), $P/Q$ ramp rate limits, and IGBT heatsink thermal mass.
- **Semiconductor Switching**: Microsecond IGBT gate turn-on/turn-off times, dead-time distortion, and DC-bus voltage ripple are not computed.
- **Harmonic Injection**: The PCS produces no harmonic current and no negative-sequence current; the model is a positive-sequence fundamental-frequency representation.

### 2.4 Electrical Network & Grid Physics

- **Single-Phase Equivalent Phasor Solver**: The electrical network calculates balanced 3-phase power flow using `SimplePhasorPowerFlowSolver`.
- **Asymmetrical & Unbalanced Grids**: Phase unbalance (e.g. single-phase line-to-ground faults) and harmonic distortion ($THD_V$) are not modeled.
- **External Power-Flow Solvers**: `PandaPowerOpenDSSInterfaceStub` is a **stub**. It defines the integration contract but computes nothing. PandaPower and OpenDSS are **NOT IMPLEMENTED**.

### 2.5 CIL Protocol Gateway & Network Scope

- **Loopback Isolation**: The Modbus TCP CIL server is bound strictly to loopback (`127.0.0.1:5020`).
- **Protocol Support**: Only Modbus TCP holding registers are implemented. The OPC UA and MQTT adapter contracts exist as abstract interface specifications; **no adapter for either protocol is implemented**.
- **Single Controller**: The gateway models one external controller connection. Multi-client arbitration, redundant controllers and controller-failover voting are **NOT IMPLEMENTED**.

### 2.6 Historian

- **Ring Buffer Before TimescaleDB**: Telemetry is held in a bounded in-memory ring buffer and flushed to the database. The disk-overflow fallback writes append-only JSON files; it protects against silent loss but it is not a queryable time-series store.

---

## 3. Platform Scope Limitations

The mission of `AGENTS.md` §1 is broader than the delivered platform. The
following items are **NOT IMPLEMENTED** and must not be represented as
available:

| Mission item | Status |
| :--- | :--- |
| Market clearing, price formation and dispatch optimisation | `NOT_IMPLEMENTED` |
| Digital-twin calibration against field measurement | `NOT_IMPLEMENTED` |
| Warranty analysis and degradation-driven settlement | `NOT_IMPLEMENTED` |
| Hardware-in-the-loop (HIL) | `NOT_IMPLEMENTED` — a later, separately approved phase under `AGENTS.md` §2.2 |
| Standalone auxiliary-system model | `PARTIALLY_IMPLEMENTED` — auxiliary consumption is modelled inside the battery system; there is no separate auxiliary package |
| `backend/app/services/` | An empty package placeholder; it contains no service implementation |

Grid services themselves **are** implemented: seven plugins live in
`plugins/grid_services/` — FCR, aFRR, MFRR, energy arbitrage, peak shaving,
renewable smoothing and volt-var support — behind the `grid_service`
interface, with a status model and SoC-based unavailability. What is missing
is the market layer that would decide *which* service to offer at *what*
price.

The scenario framework **is** implemented: `backend/app/simulation/scenario.py`,
`scenario_runner.py` and `fault_injection.py` provide scenario definitions,
fault-event sequences, acceptance criteria and a runner that drives the plant
through them.

---

## 4. Software Engineering and Delivery Limitations

### 4.1 Frontend Test Coverage

The frontend test suite contains **4 tests in 2 files**. Every one of the 19
SCADA view components and the React hooks are untested. The measured coverage
is **4.15 % of lines, 5.95 % of functions and 0 % of branches**.

The enforced floor in `frontend/vite.config.ts` equals that measured value, so
the gate detects a regression but proves very little. The 75 % target that an
earlier revision of the CI/CD guide published was **aspirational and was never
implemented**: the configuration declared a threshold that could not be met,
and the coverage provider was not even installed, so the check could not run.

### 4.2 No End-to-End Test Suite

`AGENTS.md` §4 names Playwright for frontend end-to-end tests. **Playwright is
not configured.** The operator path — log in, read the overview, issue a
setpoint, observe the result — is never exercised automatically.

### 4.3 The Python Runtime Dependencies Are Not Pinned

`backend/requirements.txt` declares every runtime dependency with `>=`.
Two builds of the same commit can therefore resolve to different versions, and
the release archive is not byte-for-byte reproducible. `pip-audit` audits the
declared *ranges* rather than one exact build.

The **CI toolchain** is pinned to exact versions in
`backend/requirements-ci.txt`, so the linters, the type checker and the test
runner are identical in every pipeline run. The **runtime** dependencies are
not. The size of the gap was observed during the final audit: the same source
tree resolved to FastAPI 0.165 and bcrypt 5.0 on a clean Python 3.12
environment, against 0.118 and 4.x on the machine it had been developed on.
The suite passed against both, which is reassuring but is not the same as
being pinned.

The frontend **is** pinned, by `frontend/package-lock.json` and `npm ci`.

### 4.4 The ORM Metadata Is Not Compared With the Migrations

The release pipeline validates the Alembic migration graph **offline**: it
checks that the graph has exactly one head and that the whole chain renders to
SQL. It does **not** compare the ORM metadata against the migration history,
because that check requires a live database connection *and* a non-empty
`target_metadata` in `migrations/env.py`. A model column added without a
migration can therefore reach a release undetected.

### 4.5 Branch Protection Is Documented, Not Applied

The required status checks for `main` are listed in `docs/CI_CD_GUIDE.md` §3.
The branch-protection configuration itself is a property of the repository on
GitHub, not of the source code, and **must be applied by a repository
administrator**.

### 4.6 The Workflow Definitions Have Not Been Executed on GitHub

The six workflow files have been corrected and reviewed, and **their steps
have been run locally**, but no GitHub Actions run has been observed. A YAML
or expression error in a workflow is invisible until the pipeline runs.

The local execution is strong evidence but not the same evidence. The backend
gates were run on the canonical interpreter **Python 3.12**, in a clean
virtual environment built from the two requirements files exactly as the
pipeline builds it, and again on **Python 3.13** and **Python 3.14**:
formatting, linting, strict type checking, 315 tests with coverage, the
coverage policy, the migration validation, the release-version validation and
the endurance campaign all passed on all three. The frontend gates were run as
well and all passed. `pip-audit` was executed against the declared ranges and
against the fully resolved build, and reported no known vulnerabilities in
either; `npm audit --audit-level=high` reported 0 vulnerabilities.

The determinism fingerprint was identical on all three interpreters
(`58d28d0aab4cd788`), so the determinism is a property of the model rather
than of one CPython build.

**One gap remains**: the workflow *files* themselves have never been executed
by GitHub Actions. Every step they contain has been run locally, but the YAML
syntax, the expression evaluation, the action pinning and the runner's own
environment can only be confirmed by an actual run.

### 4.7 The Endurance Campaign Covers the Reference Plant Only

The nightly determinism campaign builds the 10 MW / 20 MWh reference plant.
It does not exercise every topology variant, every vendor plugin combination,
or the 50 MW / 200 MWh variant under long-duration load.

### 4.8 A Module-Level Simulation Entry Point Remains

`backend/app/api/v1/simulation_ctrl.py` keeps `set_active_simulation_engine(...)`
as a compatibility helper for the unit tests. It writes to the
application-scoped runtime under a lock, so it is not an unguarded global, but
it is a second way to reach the same state.

### 4.9 The Operator-Action Journal Is Not Dedicated or Tamper-Evident

Commands, setpoint changes, faults and configuration changes reach the
historian and the structured logs, which satisfies `AGENTS.md` §2.10 for the
simulated platform. There is no separate, append-only, tamper-evident operator
action journal. A warranty or dispute-resolution use case would require one.

### 4.10 Illustrative Parameters Are Labelled in Prose Only

`AGENTS.md` §2.14 requires illustrative parameters to be clearly labelled.
The reference topology and the plugin datasheets are labelled in the
documentation, but no schema field and no test enforce the labelling.

---

## 5. Reproducibility and Determinism Limitations

- **Determinism requires the same interpreter.** A bit-identical replay is
  guaranteed for the same source tree, the same configuration and the same
  interpreter and platform floating-point behaviour. A different CPython
  version may produce different last-bit results in floating-point
  accumulation.
- **The snapshot schema is versioned.** A snapshot is restorable within its
  schema version. Restoring across a major schema version is not supported.
- **A snapshot is not a file format.** Snapshots are transported through the
  in-process API; there is no on-disk snapshot container or a cross-version
  migration path for stored snapshots.

---

## 6. Measurement and Documentation Limitations

- **Every measurement carries a timestamp, a quality flag and a source**, but
  the platform does not implement a full measurement-uncertainty budget. The
  modelled sensor noise is a deterministic offset, not a statistical model.
- **The reference plant and the vendor plugin parameters are illustrative.**
  They are derived from public datasheets and generic engineering practice and
  have not been reconciled against a specific operator's fleet.
- **No hard real-time claim is made.** Throughput figures are measurements on
  general-purpose hardware and must not be used as a specification.
