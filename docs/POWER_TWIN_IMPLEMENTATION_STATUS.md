# PowerTwin — Implementation Status Report

## 1. Executive Overview

This document is the authoritative implementation status of the **PowerTwin
Modular Industrial BESS Simulator & Emulator Platform**, covering the repair
packages PT-001 through PT-013 and the remediation programme that followed.

All implementations operate strictly in **SIMULATION ONLY** mode
(`SIMULATION_ONLY = True`). The platform is designed for software simulation,
control-logic validation, SCADA Web HMI monitoring, and Controller-in-the-Loop
(CIL) loopback testing.

The status below is derived from the source code, the automated test results
and the delivery pipeline. Where an item is not implemented, it is marked
`NOT_IMPLEMENTED` rather than described in a way that could be read as
available. The companion documents are
`docs/POWER_TWIN_FINAL_AUDIT_REPORT.md`,
`docs/POWER_TWIN_REQUIREMENTS_TRACEABILITY.md` and
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md`.

---

## 2. Subsystem Implementation Summary

| Subsystem / Module | Status | Core Accomplishments |
| :--- | :--- | :--- |
| **Deterministic Simulation Engine** | `IMPLEMENTED_AND_TESTED` | 100 Hz integer nanosecond clock ($10\text{ ms}$ step), five-phase DAG scheduler (Grid → Controllers → PCS → Battery → BoP/POI), seeded RNG, full domain state serialization in `SimulationSnapshot`, pause/resume/step/reset/replay. The continuous runner holds an explicit lifecycle contract: **a stop is final** (no tick starts behind the back of a stop), **a start always leaves a loop that really ticks** (a superseded thread cannot clear the state of the generation that replaced it), **a step advances the clock by exactly the requested number of ticks** and stops the continuous loop to do so, and **a pause never delays a stop**. The contract is stated in `docs/04_SIMULATION_ENGINE_SPECIFICATION.md` §3.1 and asserted by `tests/test_simulation_runner.py` and `tests/test_simulation_runtime.py`. |
| **Battery & Master BMS Models** | `IMPLEMENTED_AND_TESTED` | Energy-balanced ECM battery model, usable capacity ($C_{\text{usable}}$) vs nominal capacity ($C_{\text{nom}}$), auxiliary load tracking (`unserved_aux_energy_wh`), BMS current/voltage/thermal limits, alarm deduplication, persistent fault checks, contactor interlocks. |
| **PCS Inverter & BoP Models** | `IMPLEMENTED_AND_TESTED` | Four explicit $P/Q$ values (Requested, Accepted, Actual, Measured), $P^2 + Q^2 \le S_{\text{max, eff}}^2$ circle clamping with priority, AC terminal current limits, $P/Q$ ramp rate limiters, IGBT heatsink thermal mass, transformer and switchgear models. |
| **3-Tier Control Hierarchy** | `IMPLEMENTED_AND_TESTED` | Layer A Equipment Controller state-machine startup with command verification and rollback; Layer B PPC POI voltage/power-factor regulation and proportional allocation; Layer C EMS multi-container feasibility aggregation, droop and scheduled-profile mode. |
| **Plant Topology Engine** | `IMPLEMENTED_AND_TESTED` | Single authoritative equipment instance ownership per asset, YAML topology loading, connectivity validation, multi-container and multi-PCS scaling (10 MW / 20 MWh reference plant and 50 MW / 200 MWh variant plant). |
| **Vendor Plugin Framework** | `IMPLEMENTED_AND_TESTED` | Plug-and-play plugin architecture for CATL EnerOne, Tesla Megapack, SMA Sunny Central and Sungrow SC5000 models, with manifest, capability and compatibility declaration, configuration validation and safe failure, without core engine modification. |
| **CIL Protocol Gateway** | `IMPLEMENTED_AND_TESTED` | Real Modbus TCP server bound strictly to loopback (`127.0.0.1:5020`), read-only telemetry registers (`0x0000`–`0x000C`), command write registers (`0x0064`–`0x006C`) routed to the plant EMS dispatch loop, watchdog heartbeat tracking ($5\text{ s}$ timeout), no silent fallback between real and simulated devices. |
| **Historian & Telemetry** | `PARTIALLY_IMPLEMENTED` | Non-blocking in-memory ring buffer (10,000 max capacity), zero-silent-loss disk overflow fallback, live telemetry extraction in `/api/v1/overview`, historical query API. **The running platform never writes to the store: nothing in `backend/app/` constructs the `HistorianService` or calls its recorder, so in a running deployment the historian tables stay empty and the query endpoints answer with no rows. See finding F-15 in `docs/POWER_TWIN_FINAL_AUDIT_REPORT.md` — it is OPEN and approval-gated under `AGENTS.md` §7.5.** |
| **SCADA Web HMI** | `PARTIALLY_IMPLEMENTED` | 19-view React + TypeScript SCADA frontend, interactive Single-Line Diagram, real-time telemetry display with **"SIMULATED DATA ONLY"** labelling on every view, and a login-gated platform session. **Nine of the 19 views read the backend — the plant overview, the alarms, PCS, battery-system and grid/POI views (all through `/api/v1/overview`), the simulation-control and system-settings views (through `/api/v1/info`), and the historian and warranty views (through `/api/v1/historian/**`). The other ten render the reference plant's illustrative equipment parameters, labelled as such.** The simulation view reaches **every** engine lifecycle action — Start, Pause, Stop, Single Step and Reset — each behind a confirmation modal, and it reads and sets the **wall-clock speed factor**, refusing a factor outside the permitted range without sending it. **A component suite of 176 tests in 11 files covers the entry point, the shared components, the login flow, the telemetry hook, the API client and every SCADA view (98.02 % line, 99.21 % function, 98.03 % statement and 88.02 % branch coverage), and the enforced Vitest floors are 75 % globally with tighter per-directory floors.** |
| **Security & API RBAC** | `IMPLEMENTED_AND_TESTED` | JWT HTTP Bearer token authentication, deny-by-default `require_permission(...)` middleware, restrictive CORS rules, startup safety-invariant validation (simulation-only, loopback binding, secret strength, database password strength, login rate limiting), in-memory platform session bridge (token never persisted to client storage). |
| **CI/CD & Release Pipeline** | `IMPLEMENTED_AND_TESTED` | Six GitHub Actions workflows with pinned action commit SHAs, explicit job permissions, `timeout-minutes` on every job, an **enforced** coverage policy with global and per-domain floors, an offline migration-graph validation, release-version format validation, a reproducible SPDX-2.3 SBOM shipped with its dependency inventories and checksums, a nightly determinism and drift campaign, a **hash-pinned Python runtime lock** installed with `--require-hashes` everywhere, a **pinned CI toolchain** in `backend/requirements-ci.txt`, an **ORM-versus-migration drift gate** that builds the schema in an ephemeral TimescaleDB service container and compares it with the ORM metadata, and every tool configuration — Ruff, pytest, coverage — pinned inside the repository **at the level the tool is invoked from**, so that a local run and a pipeline run cannot disagree. The deployed container images are **multi-stage**, **digest-pinned**, carry no build toolchain and no package installer in their runtime layer, are proven in the build to contain exactly the hash-verified packages of the lock and nothing else, apply the newest published distribution patches, and are scanned under two policies that separate the advisories this project controls from the ones only the distribution can fix. |
| **Grid Services Framework** | `IMPLEMENTED_AND_TESTED` | Seven plugins in `plugins/grid_services/` — FCR, aFRR, MFRR, energy arbitrage, peak shaving, renewable smoothing and volt-var support — behind the `grid_service` interface, with a status model, SoC-based unavailability and a performance score. |
| **Scenario & Fault-Injection Framework** | `IMPLEMENTED_AND_TESTED` | `backend/app/simulation/scenario.py`, `scenario_runner.py` and `fault_injection.py`: scenario definitions, timed fault-event sequences, acceptance criteria, and a runner that drives the plant through them. |
| **Energy-Market Clearing & Optimisation** | `NOT_IMPLEMENTED` | Market clearing, price formation and dispatch optimisation. The platform has an energy-arbitrage plugin and an EMS scheduled-profile mode, but no market model. |
| **Digital-Twin Calibration** | `NOT_IMPLEMENTED` | Reconciliation of the simulation against field measurement. No `calibration` package exists. |
| **Warranty Analysis** | `NOT_IMPLEMENTED` | Degradation-driven settlement and warranty workflows. No `warranty` package exists. |
| **Hardware-in-the-Loop (HIL)** | `NOT_IMPLEMENTED` | A later, separately approved phase under `AGENTS.md` §2.2. No HIL package, and deliberately no default route, protocol connection or credential that could target real equipment. |
| **Frontend End-to-End Testing** | `IMPLEMENTED_AND_TESTED` | A Playwright project (`frontend/playwright.config.ts`, specs in `frontend/e2e/`) drives the **built** HMI in Chromium against a **hermetic mock platform** that answers every `/api/v1/**` request inside the browser, aborts unmodelled paths and blocks every host but the loopback preview server. The specs cover the operator path (log in → read the overview → pause the engine behind its confirmation → observe the result → log out) and the full engine lifecycle (start and stop the engine from the screen, each behind its confirmation), the wall-clock speed factor (the factor in force is displayed and a factor the operator asks for is confirmed by name and dispatched as `SET_SPEED`), and the safety posture (the token stays in memory, a backend that is not ready is reported as disconnected, a refused action is reported as a failure). The suite runs in the `Frontend Lint, Test & Build` pipeline job, and `tests/test_deployment_images.py` asserts that it cannot be silently removed. |
| **OPC UA / MQTT Adapters** | `NOT_IMPLEMENTED` | The adapter contract exists in `backend/app/communication/adapter.py`; only the Modbus TCP adapter is implemented. |

---

## 3. Enforced Quality Gates

Unlike an earlier revision of this document, each gate below is **enforced by
the pipeline** and is backed by a test, not only by a document.

| Gate | Where it is enforced | Where it is tested | Failure mode |
| :--- | :--- | :--- | :--- |
| Formatting | `ruff format --check backend plugins tests scripts deployment` | — | Job fails |
| Linting | `ruff check backend plugins tests scripts deployment`, rule set pinned in `ruff.toml` and `backend/pyproject.toml`, one declared style for the whole repository | `tests/test_tool_configuration.py` | Job fails |
| Type checking | `mypy --config-file backend/pyproject.toml backend plugins scripts` (`strict = true`) | — | Job fails |
| Unit and integration tests | `pytest` with unraisable exceptions promoted to errors | The suite itself (501 tests) | Job fails |
| Backend coverage policy | `scripts/check_coverage.py coverage.json` | `tests/test_ci_scripts.py` | Job fails |
| Frontend coverage policy | `frontend/vite.config.ts` thresholds, applied by `npm run test:coverage` | The Vitest suite (176 tests) | Job fails |
| Frontend type checking | `npm run lint` (`tsc --noEmit`), covering `src/`, `e2e/` and `playwright.config.ts` | — | Job fails |
| Frontend end-to-end path | `npm run test:e2e` (Playwright against the built artefact on the loopback interface, with a hermetic mock platform) | The Playwright suite (8 specs); the configuration is asserted by `tests/test_deployment_images.py` | Job fails |
| Interpreter compatibility | Matrix on Python 3.13 and 3.14, `fail-fast: false` | The suite itself | Job fails |
| Release version format | `scripts/validate_release_version.py` | `tests/test_ci_scripts.py` | Job fails before anything is built |
| Migration graph | `scripts/validate_migrations.py` (offline) | `tests/test_ci_scripts.py` | Job fails before the archive is assembled |
| ORM-versus-migration drift | `alembic upgrade head` and `alembic check` against an ephemeral TimescaleDB service container in the release job | `tests/test_deployment_images.py` | Job fails before the archive is assembled |
| SBOM validity and reproducibility | `scripts/generate_sbom.py` | `tests/test_ci_scripts.py` | Job fails before the archive is assembled |
| Determinism and drift | `scripts/endurance_campaign.py` — two runs, one seed, compared fingerprints | `tests/test_ci_scripts.py` | Nightly job fails |
| Dependency audit | `pip-audit` and `npm audit --audit-level=high` | — | Job fails |
| Container and secret scanning | Trivy (both deployed images, split into an operating-system policy that requires a published fix and an application-package policy that requires none), TruffleHog, CodeQL | — | Job fails |
| Deployed image hygiene | Multi-stage build, digest-pinned base images, `apt-get upgrade`, no build toolchain and no package installer in the runtime layer | `tests/test_deployment_images.py` | Job fails before the image is published |
| Dependency lock fidelity | `scripts/check_dependency_lock.py` compares the lock with the declared ranges | `tests/test_ci_scripts.py` | Job fails |
| Deployed dependency set | `scripts/verify_locked_environment.py` in strict mode inside the container build; in the default mode in the pipeline | `tests/test_ci_scripts.py` | The image does not build, or the job fails |
| Container smoke test | The built image is started, its own health probe is awaited and the `SIMULATION_ONLY` invariant of the running service is asserted | — | Job fails |
| Reproducible toolchain | `backend/requirements-ci.txt`, pinned to exact versions | — | A tool upgrade is an explicit, visible change |

---

## 4. Implementation Status Definitions

- **`IMPLEMENTED_AND_TESTED`**: Feature is fully implemented, integrated into the execution loop, and verified by passing automated unit, property-based, and integration tests.
- **`IMPLEMENTED_PARTIALLY_TESTED`**: Feature is fully implemented and integrated, but the automated test coverage is materially smaller than the feature. The gap is stated explicitly wherever it appears.
- **`IMPLEMENTED_NOT_FULLY_VALIDATED`**: Feature is implemented but pending independent physical laboratory or field test validation.
- **`PARTIALLY_IMPLEMENTED`**: Basic interface exists; advanced features planned for future releases.
- **`NOT_IMPLEMENTED`**: Feature is planned for future development phases. It is marked as such and must not be represented as available.
- **`NOT_TESTED`**: Code exists but lacks automated test coverage.

---

## 5. Items Carried Forward as Remaining Work

| # | Item | Severity |
| :--- | :--- | :--- |
| 1 | Apply the documented branch protection to `main` (administrator action — the rule set is now executable, see below) | Medium |
| 2 | Implement the energy-market, calibration and warranty roadmap items | Medium |

**Audit finding F-04 — "the branch protection of `main` is documented but not
applied" — is partially addressed, and still needs one administrator
command.** The rule set is no longer a prose checklist: it is declared once in
`scripts/apply_branch_protection.py`, can be printed without touching the
network (`--dry-run`), is applied and then **read back** from GitHub, and the
script exits non-zero if what is in force is looser than what was documented.
Three tests hold the documentation, the declaration and the workflow job
names together, so a renamed job fails the suite rather than silently
blocking every merge. What remains is the application itself, which needs a
token with `administration` permission on the repository:

```bash
GITHUB_TOKEN=<your-token> python scripts/apply_branch_protection.py
```

The repository currently has **no ruleset** — `GET /repos/faroub/PowerTwin/rulesets`
returns an empty list — and the legacy branch-protection endpoint needs a
token to read, so the administrator's run is also the verification.

**A failing pipeline now names the test that failed.** The backend jobs
write a JUnit report and publish it as **check-run annotations**
(`scripts/summarize_pytest_failures.py`), and the console output is appended
to the job summary. This matters because the job log can only be downloaded
with repository administration permission and the artifacts need
authentication too: without the annotations, a red pipeline told nobody but
an administrator what had gone wrong. The report is published with
`if: always()`, so it appears after a failing run as well as after a
successful one, and the pytest invocation uses `set -o pipefail`, so `tee`
cannot swallow the exit status of a failing suite. Both properties are
asserted by `tests/test_ci_scripts.py`.

**The coverage tool is now pinned as well.** `pytest-cov` only states a lower
bound for `coverage`, the tool that produces the report the coverage policy
decides on, so the pipeline was resolving it afresh on every run. It is
pinned in `backend/requirements-ci.txt` like the rest of the toolchain.

**Audit finding F-09 — "the dedicated operator-action journal" — is closed.**
The platform now has one dedicated, append-only, tamper-evident
journal (`backend/app/core/operator_journal.py`): a JSON Lines file that is
only ever opened in append mode, in which every entry carries the SHA-256
hash of its predecessor and of its own canonical content. Changing, removing
or reordering an entry breaks the chain, and `verify()` reports the first
break. The chain continues across a restart, the journal is process-scoped so
that two applications cannot write two trails, and it is always on because
`AGENTS.md` §2.10 requires the record. Commands and setpoint changes,
configuration changes, authentication events, faults and the operator's own
actions — including the ones that were refused — all flow through it.
`tests/test_operator_journal.py` covers the properties a warranty or dispute
analysis relies on.

The migration environment silenced the application's loggers as a side
effect — `logging.config.fileConfig` disables every logger that already
exists — which would have switched off the audit trail without a word. That
is fixed, and a test fails if it regresses.

**Audit finding F-08 — "the module-level simulation entry point" — is
closed.** The runtime is the single write path to the plant and the
engine: a plant is attached with `SimulationRuntime.attach_plant` and
detached with `SimulationRuntime.drop`, and both module-level
`set_active_simulation_engine` helpers are gone. The unit tests construct
their plant through the runtime the API itself resolves, and
`tests/test_simulation_runtime.py` asserts that the helpers cannot return.

**The line-length unification of that list is closed.** The whole repository
is now linted with one declared style: the same line length (100), the same
target version, the same rule selection and `E501` active in every tree. The
`deployment/` tree, which carried no pinned configuration at all, is covered
like the others. `tests/test_tool_configuration.py` fails when the two Ruff
declarations diverge or when the pipeline stops linting one of the
repository's Python trees.

**Item 1 of an earlier revision — "Add `target_metadata` to the migrations and
restore the ORM-versus-migration comparison" — is closed.** The Alembic
environment declares the ORM metadata and excludes the index that TimescaleDB
owns, the release job builds the schema and compares it with the ORM against
an ephemeral TimescaleDB service container, and the ORM now declares exactly
the index set the migrations create. A model that is changed without a
migration fails the release. Two limits remain and are recorded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.4: Alembic does not compare primary
keys, and the gate runs at release time rather than on every pull request.

**The drift gate has now been executed, and its negative case verified.** The
release job's TimescaleDB service container and its two Alembic commands had
never run on a GitHub runner, because publishing a release requires pushing a
`v*` tag. The commands were therefore rehearsed locally against the **same
digest-pinned image** the workflow uses, with the same environment variables:
`alembic upgrade head` applied `001_initial_schema` and `002_user_accounts`,
and `alembic check` reported *"No new upgrade operations detected."* and
exited zero. The gate was then probed with an undeclared table added to the
migrated schema: `alembic check` detected it and **failed with exit code
255**, so the gate refuses a release whose models and migrations disagree
rather than passing silently. The rest of that job — the artifact upload, the
SBOM, the checksums and the image builds — has still not been executed on a
runner, and that remains recorded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.4.

**The `illustrative` schema marker of that list is closed.** Every topology
configuration model now carries an `illustrative: bool` field that defaults to
`True`, the plant-level marker is derived from the items and refuses an
under-labelled plant, the plant factory carries the marker into the runtime
equipment metadata, both shipped example configurations state it explicitly,
and `tests/test_illustrative_parameters.py` asserts all of that. The label
does not yet reach the operator's screen, because the HMI has no
topology-configuration API; that is recorded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.10.

**Item 2 of an earlier revision — "Build the frontend component suite and the
Playwright end-to-end path, then raise the enforced floor" — is closed.** The
component suite measures 176 tests and 98.02 % line coverage with an enforced
floor of 75 %, the Playwright project drives the built HMI against a hermetic
mock platform in the pipeline, and the properties of both are asserted from
`tests/test_deployment_images.py` so that they cannot be silently removed.

**A red pipeline turned out to be a concurrency defect in the simulation
runner, and it is closed.** The `backend-ci` job on Python 3.12 failed while
the same suite passed on 3.13 and 3.14 without coverage instrumentation. The
difference was timing, not the code: the 3.12 job is the only one that runs
the suite with `--cov`, which widens the window in which three lifecycle
races of the runner could occur. A tick could start behind the back of a
stop, which left the engine `PAUSED` after a stop that had been
acknowledged; a start could adopt the execution thread of the previous
generation while that thread was on its way out, which left the runner
reporting a running loop that nothing drove (measured in 223 of 3000 rapid
start/stop/start cycles); and a step measured its baseline against a
concurrently advancing clock, which made the observable delta
nondeterministic.

The runner now holds an explicit lifecycle contract — a stop is final, a
start always leaves a running loop, a step advances the clock by exactly the
requested number of ticks — stated in
`docs/04_SIMULATION_ENGINE_SPECIFICATION.md` §3.1 and asserted by
`tests/test_simulation_runner.py` and `tests/test_simulation_runtime.py`.
The interleavings that break the contract are forced with a gated step and a
task that holds a tick open, so the tests do not depend on the timing of a
contended machine to reach the broken ordering; the new tests fail against
the unrepaired runner and pass against the repaired one.

**The STEP control command now means what it says.** The tick count is
accepted under the names `steps` and `ticks`, so a client that sends
`ticks` gets the count it asked for instead of having the field ignored and
the default applied. A count of zero, a negative count or a count above
`MAX_STEP_TICKS` (1000, i.e. 10 s of simulated time at the 100 Hz tick
rate) is **refused** with HTTP 400 and recorded in the operator-action
journal as `REJECTED` / `INVALID_STEP_COUNT`; it is not corrected into a
different command. The bound keeps a synchronous control command within a
duration an operator can wait for, and the reasons it exists are recorded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.12.

**The engine state the HMI shows the operator now comes from the engine that
owns the plant.** `GET /api/v1/info` is where the Simulation Control screen
takes the engine state from, and it used to resolve that state through the
module-level fall-back runtime — the instance for callers without an
application handle — instead of the application-scoped runtime that holds the
plant. The endpoint therefore answered `NOT_CONNECTED` while the Plant
Overview reported the running plant. It now resolves the runtime from the
request, exactly as the Plant Overview does, and the divergent second
implementation of the engine status is removed. The regression test
`tests/test_startup.py::test_system_info_reports_the_engine_that_owns_the_plant`
asserts that both endpoints describe the same engine and fails against the
unrepaired code with `assert 'NOT_CONNECTED' == 'RUNNING'`. The reasons are
recorded in `docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.14 and in
`docs/POWER_TWIN_FINAL_AUDIT_REPORT.md` F-13.

**The wall-clock speed factor is bounded everywhere and reachable from the
screen.** The engine specification documents the factor as running from
$0.1\times$ to $100\times$, with `0.0` reserved for maximum headless
execution speed, but the implementation enforced neither end: a factor of
`1e9` was accepted by the configuration model, the engine, the runner and
the control endpoint alike. The range now lives in one place —
`MIN_SPEED_FACTOR` (0.0) and `MAX_SPEED_FACTOR` (100.0) in
`backend/app/simulation/config.py` — and the single `validate_speed_factor()`
function that decides the question is applied at **all four** boundaries
that accept a factor, so a factor refused by the endpoint cannot reach the
engine by another route. The endpoint refuses an out-of-range factor with
HTTP 400 and records the refusal in the operator-action journal as
`REJECTED` / `INVALID_SPEED_FACTOR`; it does not substitute a different
factor, because a silent substitution would leave the operator believing
the clock is paced the way they asked.

The factor was also unreachable from the HMI: `SET_SPEED` existed in the
API and not on the screen, and the card that purported to report the factor
showed a hard-coded `1.0 x`. The card now shows the factor **in force** —
the one the clock is actually paced with, carried in the engine status — and
a **Wall-Clock Pacing** card sets it, refusing an out-of-range factor
without sending it and naming the requested factor in the confirmation
modal. The reasons are recorded in `docs/POWER_TWIN_KNOWN_LIMITATIONS.md`
§4.13 and in `docs/POWER_TWIN_FINAL_AUDIT_REPORT.md` F-14.
