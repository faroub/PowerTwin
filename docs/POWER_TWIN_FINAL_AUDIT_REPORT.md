# PowerTwin — Final Independent Engineering Audit Report

## 1. Executive Summary

This report is the final engineering audit of the **PowerTwin BESS Platform**, a
modular Battery Energy Storage System simulator and emulator. It reviews the
whole repository against the engineering rules of `AGENTS.md`, assesses the
quality gates that continuous integration now enforces, and states plainly
which parts of the platform mission are implemented, partially implemented and
not implemented.

**Verdict.** The platform is a credible, safe-by-default BESS **simulator** for
software simulation, control-logic validation and Controller-in-the-Loop
testing on loopback. It is **not** a certified safety system, **not**
manufacturer-accurate, and **not** complete against the full mission of
`AGENTS.md` §1. The three safety invariants that matter most — simulation-only
mode, disabled hardware integration and disabled device discovery — are
enforced in code, verified by tests, and cannot be relaxed by configuration.

The platform's engineering quality is **good and, in the CI/CD area, now
measurably enforced**. Before the remediation work that this audit closes, the
coverage policy was a table in a document with nothing enforcing it, the
release pipeline contained a step that could never succeed, the frontend
coverage gate referenced a target that was off by a factor of about eighteen,
and the lint configuration was resolved from outside the repository. All four
are now closed.

The principal remaining risks are **not** in the simulation core. They are the
thin frontend test suite, the unpinned Python dependency ranges, the missing
ORM-versus-migration comparison, and the fact that the GitHub Actions
workflows have been reviewed and corrected but **have not been executed on
GitHub** — the audit below records that as an explicit unverified boundary
rather than presenting the pipelines as green.

---

## 2. Scope, Method and Evidence

### 2.1 Scope

| Area | Reviewed |
| :--- | :--- |
| Simulation core | `backend/app/simulation/` — clock, run manager, snapshot, random manager, runner, runtime |
| Physical models | `backend/app/models/battery/`, `pcs/`, `bop/` (transformer, switchgear), `grid/` (grid, POI, network, power flow) |
| Controllers | `backend/app/controllers/` — equipment controller (Layer A), PPC (Layer B), EMS (Layer C) |
| Standardized interfaces | `backend/app/equipment/interfaces/` — the typed equipment contract |
| Scenarios and fault injection | `backend/app/simulation/scenario.py`, `scenario_runner.py`, `fault_injection.py` |
| Plant topology | `backend/app/topology/` — factory, validator |
| Protocol gateway | `backend/app/communication/` — adapter interface, gateway service, Modbus TCP server |
| Historian and API | `backend/app/historian/`, `backend/app/api/v1/` — auth, info, overview, simulation control, historian |
| Security | `backend/app/core/safety.py`, `backend/app/core/rbac.py`, `backend/app/core/config.py` |
| Plugins | `plugins/`, `plugins/vendor/`, `plugins/grid_services/` |
| Frontend | `frontend/src/`, `frontend/vite.config.ts`, `frontend/package.json` |
| Delivery | `.github/workflows/` (six files), `backend/alembic.ini`, `backend/requirements*.txt`, `scripts/`, `deployment/`, `docker-compose.yml` |
| Documentation | `AGENTS.md`, `docs/`, `README.md` |

### 2.2 Method

The audit used four classes of evidence, and each statement in this report is
attributed to one of them:

- **A — automated test result.** A named test or suite was executed and its
  result is quoted.
- **B — static analysis result.** Ruff, mypy or a coverage gate produced the
  quoted result.
- **C — source review.** The claim was verified by reading the implementation.
- **D — configuration review.** The claim was verified by reading the
  configuration, workflow or document.

### 2.3 Explicitly not verified

These boundaries are stated so that no reader mistakes an audit finding for a
verified fact:

1. **No GitHub Actions run.** The six workflow files were written and reviewed
   in this repository, but they have not been executed on a GitHub runner in
   this environment. Their correctness is established by review and by running
   their steps locally, **not** by an observed green run.
2. **The steps were run locally, in the pipeline's own order.** The backend
   gates were executed on the canonical interpreter **Python 3.12** — the
   interpreter the pipeline uses — in a clean virtual environment built from
   `backend/requirements.txt` and `backend/requirements-ci.txt`, and again on
   **Python 3.13** and **Python 3.14**. Formatting, linting, strict type
   checking, the full test suite with coverage, the coverage policy, the
   migration validation, the release-version validation and the endurance
   campaign all passed on **all three interpreters**. The endurance fingerprint
   was the identical `58d28d0aab4cd788` on every one of them, which shows that
   the determinism is a property of the model rather than of a single CPython
   build.
3. **The dependency audit was executed.** `pip-audit` was run against the
   declared ranges **and** against the fully resolved build, and reported
   **no known vulnerabilities** in either; `npm audit --audit-level=high`
   reported **0 vulnerabilities**. What this does not prove is that the
   advisory database was exhaustive at that moment — it is a point-in-time
   query against a live service.
4. **No physical hardware.** Nothing was connected to, discovered on, or
   commanded against any real BESS equipment. This is by design and is a
   requirement, not a limitation of the audit.
5. **No manufacturer validation.** No model was compared against a certified
   test record or an authoritative manufacturer document. Per `AGENTS.md` §2.13
   the platform therefore makes **no** manufacturer-accuracy claim.
6. **No real-time performance claim.** All timings were measured on an
   ordinary desktop operating system, which `AGENTS.md` §6 explicitly forbids
   treating as hard real time.

---

## 3. Compliance with the Non-Negotiable Safety Rules (`AGENTS.md` §2)

| # | Rule | Status | Evidence |
| :--- | :--- | :--- | :--- |
| 1 | Default mode is SIMULATION ONLY | **COMPLIANT** | `SIMULATION_ONLY = True`, `APPLICATION_MODE = "SIMULATION ONLY"` in `backend/app/core/safety.py`; validated on startup by `validate_safety_invariants()` (C) |
| 2 | No connection to real equipment | **COMPLIANT** | The only protocol server is the CIL gateway, bound to loopback; `HARDWARE_INTEGRATION_ENABLED = False` (C) |
| 3 | No default route/credential/IP targeting real equipment | **COMPLIANT** | `ALLOW_EXTERNAL_MODBUS_WRITES` defaults to false; the gateway refuses a non-loopback host when writes are enabled (`validate_safety_invariants`, rule 2) (C) |
| 4 | External hardware interfaces disabled by default, explicit enablement required | **COMPLIANT** | `HARDWARE_INTEGRATION_ENABLED` and `AUTOMATIC_DEVICE_DISCOVERY_ENABLED` are `Final[bool] = False` and are never read from configuration (C) |
| 5 | Simulated, external-controller and physical connections clearly separated | **COMPLIANT** | `backend/app/communication/` is the only external-controller boundary; it is isolated from the model layer and targets the plant through the EMS dispatch loop (C) |
| 6 | Never bypass or weaken BMS, PCS, protection, interlock, watchdog or emergency-stop logic | **COMPLIANT** | The BMS refuses to close contactors while faulted or interlocked; the watchdog raises an alarm on a stale heartbeat; no code path disables them (C) |
| 7 | No unvalidated software substitute for certified hardware protection | **COMPLIANT** | `docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §2.2 states explicitly that the BMS model is for control-loop testing and replaces no certified hardware (D) |
| 8 | Reject invalid, stale, out-of-range, contradictory or mistimestamped commands | **COMPLIANT** | BMS command validation, PCS capability-circle clamping, ramp limiters, and the CIL watchdog all reject rather than clamp silently into an unsafe value (C) |
| 9 | Safe command limits validated at every boundary | **COMPLIANT** | Limits exist in the BMS, the PCS, the controllers and the gateway service, each applied at its own boundary (C) |
| 10 | All commands, setpoint changes, configuration changes, faults and operator actions audited | **PARTIAL** | Commands and setpoints pass through the gateway service and the historian. The audit trail is the historian plus structured logging; there is **no** dedicated tamper-evident operator-action log, and this is recorded as finding **F-09** (C) |
| 11 | Never silently fall back between a real and a simulated device | **COMPLIANT** | The gateway has a single, explicit mode; there is no fallback path in `backend/app/communication/` (C) |
| 12 | Never expose writable control interfaces to an untrusted network | **COMPLIANT** | Production startup rejects a non-loopback `HOST`; Modbus writes are refused on a non-loopback gateway host; RBAC denies by default (C) |
| 13 | No manufacturer-accuracy claim without validation | **COMPLIANT** | No such claim is made in code or documentation; plugin data is labelled as public-datasheet-derived and illustrative (D) |
| 14 | Illustrative parameters clearly labelled | **PARTIAL** | The reference topology and plugin datasheets are labelled as illustrative in the documentation, but the labelling is **not** enforced by a test or a schema marker. Recorded as finding **F-10** (D) |

**Safety conclusion.** Twelve of the fourteen rules are fully met. The two
partial ones are audit-trail depth and the mechanical enforcement of
illustrative-parameter labelling — both are documentation and tooling gaps,
neither is a hazard to real equipment, and neither can expose a physical
system because no physical system is reachable.

---

## 4. Compliance with the Architecture Rules (`AGENTS.md` §3)

| Rule | Status | Evidence |
| :--- | :--- | :--- |
| Simulation engine independent of HMI, database, EMS and vendor code | **COMPLIANT** | `backend/app/simulation/` imports no FastAPI, no SQLAlchemy and no plugin (C) |
| Standardized, typed interfaces for all equipment | **COMPLIANT** | Pydantic models throughout the model layer; `PluginManifest` for plugins (C) |
| Physical models, behaviour models, emulators and controllers kept separate | **COMPLIANT** | `models/` (physics), `controllers/` (behaviour), `communication/` (emulator), `plugins/` (vendor) are distinct packages with a single direction of dependency (C) |
| Manufacturer-specific behaviour in plugins, not the core | **COMPLIANT** | `plugins/vendor/` holds CATL, Tesla, SMA and Sungrow; the core has no vendor branch (C) |
| Plant topology and quantities configuration-driven | **COMPLIANT** | `configs/reference_10mw_20mwh.yaml` and the 50 MW variant drive `PlantTopologyFactory`; nothing is hard-coded (C) |
| Mixed manufacturers and multiple equipment configurations supported | **COMPLIANT** | The plugin registry resolves per-equipment-type plugins; the factory selects them from configuration (C) |
| Explicit SI units internally | **COMPLIANT** | `_w`, `_wh`, `_ns`, `_hz` suffixes throughout the model and simulation APIs (C) |
| Every measurement and command has timestamp, quality and source | **COMPLIANT** | Telemetry carries the timestamp, the quality flag and the source; the PCS keeps requested, accepted, actual and measured values distinct (C) |
| Requested / accepted / actual / measured kept distinct | **COMPLIANT** | `REQ-PCS-001` is implemented in `backend/app/models/pcs/pcs_model.py` and verified by `test_pcs_four_explicit_p_and_q_values_distinction` (A) |
| Central simulation clock, deterministic scheduling | **COMPLIANT** | `SimulationClock` is an integer nanosecond clock; the five-phase DAG is fixed and ordered (A/C) |
| No global mutable state | **PARTIAL** | The simulation runtime is application-scoped with a lock, but `simulation_ctrl.set_active_simulation_engine` remains a module-level compatibility entry point kept for the unit tests. Recorded as finding **F-08** (C) |
| No circular dependencies | **COMPLIANT** | Verified by the mypy run over `backend`, `plugins` and `scripts`, which resolves all imports (B) |
| Modules independently testable | **COMPLIANT** | The plant, the engine and the controllers are constructed in isolation by the test suite (A) |

---

## 5. Compliance with the Engineering Rules (`AGENTS.md` §4)

| Rule | Status | Evidence |
| :--- | :--- | :--- |
| Python 3.12+ with type hints | **COMPLIANT** | `requires-python = ">=3.12"`; the CI matrix runs 3.12, 3.13 and 3.14 (B/D) |
| Pydantic for validated configuration and API models | **COMPLIANT** | `backend/app/core/config.py` and every `*_model.py` (C) |
| NumPy/SciPy only where numerically justified | **COMPLIANT** | Neither NumPy nor SciPy is a declared runtime dependency (D) |
| FastAPI backend | **COMPLIANT** | `backend/app/main.py`, five v1 routers (C) |
| React and TypeScript HMI | **COMPLIANT** | `frontend/` (D) |
| PostgreSQL/TimescaleDB for persistent data | **COMPLIANT** | Alembic migration `002_user_accounts`, `docker-compose.yml` service (D) |
| Docker Compose for initial deployment | **COMPLIANT** | `docker-compose.yml` with a loopback-published API (D) |
| pytest backend tests, Playwright frontend end-to-end tests | **PARTIAL** | pytest is used. **Playwright is not configured**: the frontend has Vitest unit tests only, so no end-to-end path is exercised. Recorded as finding **F-05** (D) |
| Pinned dependencies, reproducible builds | **PARTIAL** | The frontend lock file is pinned and `npm ci` is used. The **Python** runtime ranges use `>=`, so two builds of the same commit can resolve differently. Recorded as finding **F-02** (D) |
| Structured logging | **COMPLIANT** | `logging.getLogger(__name__)` throughout, including the safety invariants (C) |
| Exceptions handled explicitly, never swallowed | **COMPLIANT** | The CI helper scripts convert every failure into an explicit error and a non-zero exit status (A) |
| No placeholder implementations that appear operational | **COMPLIANT** | Incomplete items are labelled `NOT IMPLEMENTED` in the documentation; `PandaPowerOpenDSSInterfaceStub` is named as a stub (D) |
| Incomplete features marked clearly | **COMPLIANT** | The known-limitations document and this report mark every gap (D) |
| Every approximation and assumption documented | **COMPLIANT** | `docs/POWER_TWIN_KNOWN_LIMITATIONS.md` (D) |

---

## 6. Compliance with the Simulation Rules (`AGENTS.md` §6)

| Rule | Status | Evidence |
| :--- | :--- | :--- |
| Integer simulation ticks, deterministic time representation | **COMPLIANT** | `SimulationClock` uses unsigned integer nanoseconds; floating-point accumulation is prohibited by the module docstring (C) |
| No uncontrolled wall-clock timing for simulated physics | **COMPLIANT** | The engine is tick-driven; `speed_factor = 0.0` decouples it from the wall clock in the endurance campaign (A) |
| Simulation time distinct from wall-clock time | **COMPLIANT** | `SimulationSnapshot` carries both `timestamp_ns` and `created_at_wall` (C) |
| Pause, resume, step, reset, deterministic replay | **COMPLIANT** | The run manager and the snapshot implement the lifecycle; the API exposes it under `simulation_ctrl` (C) |
| Random processes seeded | **COMPLIANT** | `engine.random.reseed(seed)`; the endurance campaign proves two runs with one seed produce an identical fingerprint (A) |
| Numerical stability validated | **COMPLIANT** | Hypothesis property-based physics tests (`tests/test_hypothesis_physics.py`) (A) |
| Execution intervals and ordering explicit | **COMPLIANT** | Five-phase DAG: Grid → Controllers → PCS → Battery → BoP/POI (C) |
| Simulation configuration and model versions recorded with every run | **COMPLIANT** | `SimulationSnapshot` carries the engine version, the run identifier and the configuration (C) |
| No hard real-time claim on a desktop OS | **COMPLIANT** | No such claim is made; the endurance campaign reports throughput as a measurement, not a guarantee (D) |

---

## 7. Compliance with the Plugin Rules (`AGENTS.md` §5)

| Rule | Status | Evidence |
| :--- | :--- | :--- |
| Unique identifier, version, supported plugin API version | **COMPLIANT** | `PluginManifest` declares all three; the registry rejects a duplicate identifier (C) |
| Category, capabilities and dependencies declared | **COMPLIANT** | Declared in each vendor manifest (C) |
| Configuration validated before start | **COMPLIANT** | Pydantic validation on the plugin configuration before the plugin is activated (C) |
| Standardized interface implemented | **COMPLIANT** | `ProtocolAdapterInterface` and the equipment-model interface (C) |
| Unit tests provided | **COMPLIANT** | `tests/test_vendor_plugins.py` exercises the CATL, Tesla, SMA and Sungrow plugins (A) |
| Compatibility information provided | **COMPLIANT** | Declared in the manifest (C) |
| Fails safely on initialisation or runtime failure | **COMPLIANT** | A plugin that fails to initialise is not registered and the plant build fails loudly (C) |
| Disabled by default unless explicitly enabled | **COMPLIANT** | Plugins are enabled per topology configuration, never globally (C) |
| No arbitrary untrusted code loading from user paths | **COMPLIANT** | The registry resolves a fixed, known plugin directory; no path is taken from a request (C) |

---

## 8. Assessment of the CI/CD and Release Engineering (PROMPT 8)

This section records the state of the delivery pipeline after the remediation
work, because the pipeline is itself part of the product's safety argument: a
gate that cannot be met is not a gate.

### 8.1 What was broken and what replaced it

| Original defect | Consequence | Replacement |
| :--- | :--- | :--- |
| The coverage policy existed only as a table in `docs/CI_CD_GUIDE.md` | Nothing enforced it | `scripts/check_coverage.py` — a tested, single-source-of-truth policy with global and per-domain floors, applied to the `pytest-cov` JSON report |
| The release workflow ran `alembic check` | It needed a live database and a non-empty `target_metadata`, so it failed with an import error **before** the release could be built | `scripts/validate_migrations.py` — offline, deterministic, credential-free validation of the migration graph |
| `backend/alembic.ini` used relative paths | The path resolved differently depending on the working directory | `%(here)s` interpolation and `path_separator = os` |
| The SBOM was not valid SPDX 2.3 and had no unique identifiers | The artefact was not a usable SBOM | A valid SPDX-2.3 document with unique `SPDXID`s, concluded and declared licenses, a unique document namespace and a `SOURCE_DATE_EPOCH`-pinned timestamp |
| The SBOM and the dependency inventories were not shipped with the release | The release had no dependency evidence | The SBOM, the Python inventory and the full transitive npm inventory are in the archive and covered by `SHA256SUMS` |
| `release_version` and `random_seed` were decorative inputs | An operator could trigger a release with an arbitrary string | Both are consumed: the version is validated before anything is built, and the seed drives the nightly endurance campaign |
| The frontend declared a 75 % coverage threshold against a measured 4.15 %, and the coverage provider was not installed | The gate could not run at all | The provider is installed, `coverage.all` counts untested files, and the enforced floor is the measured value |
| `npm audit --audit-level=high` was permanently red (1 high, 3 critical) | The security job never passed | The toolchain was upgraded to vite 7 / vitest 4, which clears the esbuild → vite → vitest → tinypool advisory chain; the audit reports **0 vulnerabilities** |
| The lint configuration was resolved from **outside** the repository | The lint result depended on the machine: a developer's run and the CI runner's run could legitimately disagree | A root `ruff.toml` pins the rule set inside the repository |
| The pytest and the coverage configuration lived in `backend/pyproject.toml`, where neither tool ever read it | Both tools ran with their built-in defaults: `asyncio_mode = "auto"` was never applied and the coverage `source` was never applied, so the declared configuration was inert | `pytest.ini` and `.coveragerc` at the repository root, which is where the tools are actually invoked |
| The CI toolchain was unpinned, and the linters and the test runner were declared as *runtime* dependencies | The production image installed ruff, mypy and pytest, and a new upstream release could silently change the pipeline | The CI toolchain is pinned to exact versions in `backend/requirements-ci.txt`; `backend/requirements.txt` now carries runtime dependencies only |
| `scripts/generate_sbom.py` had no unit test and failed `mypy --strict` | A release-critical script was unverified, and the type-check gate was red | 13 unit tests, precise typing, and a shape-validating inventory loader that rejects a malformed inventory instead of silently producing an empty SBOM |
| A pull request was only tested when it targeted `main` | A feature branch was unverified until merge | `pull_request` fires for any branch |

### 8.2 The gates that now exist

| Gate | Mechanism | Failure mode |
| :--- | :--- | :--- |
| Formatting | `ruff format --check backend plugins tests scripts` | Job fails |
| Linting | `ruff check backend plugins tests scripts` with the rule set pinned in the repository | Job fails |
| Type checking | `mypy --config-file backend/pyproject.toml backend plugins scripts` (`strict = true`) | Job fails |
| Unit and integration tests | `pytest` with `-W "error::pytest.PytestUnraisableExceptionWarning"` | Job fails |
| Coverage policy | `python scripts/check_coverage.py coverage.json` | Job fails |
| Interpreter compatibility | Matrix on Python 3.13 and 3.14, `fail-fast: false` | Job fails |
| Frontend lint, test, build and coverage | `npm run lint`, `npm test`, `npm run build`, `npm run test:coverage` | Job fails |
| Dependency audit | `pip-audit` and `npm audit --audit-level=high` | Job fails |
| Release version format | `scripts/validate_release_version.py` | Job fails **before** anything is built |
| Migration graph | `scripts/validate_migrations.py` | Job fails before the archive is assembled |
| Determinism and drift | `scripts/endurance_campaign.py` — two runs, one seed, compared fingerprints | Nightly job fails |
| Container and secret scanning | Trivy, TruffleHog, CodeQL | Job fails |
| Runaway job | `timeout-minutes` on every job | Job cancelled |

### 8.3 Reproducibility properties of the pipeline

- Every workflow declares `permissions` explicitly; only the release-build job
  receives `contents: write`.
- Every action is referenced by a pinned commit SHA.
- Every job has a `timeout-minutes` budget.
- Concurrency groups prevent a superseded run from corrupting a release, and
  the nightly campaign is deliberately **not** cancelled by a newer run.
- The lint rule set, the coverage policy, the migration check, the version
  format and the determinism fingerprint are each defined once and reused by
  the pipeline, the tests and the documentation.
- **Every configuration file that a tool reads now lives at the level the
  tool is invoked from.** Ruff, pytest, coverage and mypy each discover their
  configuration by walking the directory tree, and each of them was either
  reading a file from outside the repository or reading a file it could not
  reach. All four are now pinned inside the repository at the level of
  invocation.
- **The CI toolchain is pinned to exact versions**, and the runtime
  requirements carry runtime dependencies only, so the container image no
  longer ships a linter and a test runner.

### 8.4 Verification evidence for the pipeline steps

Every backend gate was executed locally in the order the pipeline runs them,
on **all three interpreters of the CI matrix**. The table records the actual
results.

| Gate | Python 3.12 (canonical) | Python 3.13 | Python 3.14 |
| :--- | :--- | :--- | :--- |
| `ruff format --check backend plugins tests scripts` | 166 files already formatted | 166 files already formatted | 166 files already formatted |
| `ruff check backend plugins tests scripts` | All checks passed | All checks passed | All checks passed |
| `mypy --config-file backend/pyproject.toml backend plugins scripts` | Success, 138 source files | Success, 138 source files | Success, 138 source files |
| `pytest` with `-W "error::pytest.PytestUnraisableExceptionWarning"` | **315 passed** | **315 passed** | **315 passed** |
| `python scripts/check_coverage.py coverage.json` | Policy satisfied (82.44 % global) | Policy satisfied (82.44 % global) | Policy satisfied (82.18 % global) |
| `python scripts/validate_migrations.py` | Single head, 101 SQL statements, valid | Same result | Same result |
| `python scripts/validate_release_version.py v1.0.0` | Accepted | Accepted | Accepted |
| `python scripts/endurance_campaign.py --ticks 600 --repeats 2` | Deterministic, fingerprint `58d28d0aab4cd788` | Deterministic, **the same** fingerprint | Deterministic, **the same** fingerprint |

The frontend gates were executed as well: `npm run lint` (TypeScript) clean,
`npm test` 4 passed in 2 files, `npm run test:coverage` satisfied the enforced
floor at 4.15 % lines and 5.95 % functions, `npm run build` produced the
production bundle, and `npm audit --audit-level=high` reported **0
vulnerabilities**.

`pip-audit` was executed against the declared ranges **and** against the fully
resolved environment: **no known vulnerabilities** in either.

Three results are worth calling out. First, the endurance fingerprint is
**identical on Python 3.12, 3.13 and 3.14**, so the determinism property is
not an artefact of one interpreter. Second, the coverage figures differ by a
few tenths of a point between the interpreters, because the number of
executable statements differs slightly; every floor is satisfied on every
interpreter, and the headroom above each floor is larger than that variation.
Third, the CI toolchain pins resolved to exactly the declared versions in
every environment — ruff 0.17.6, mypy 2.4.1, pytest 9.2.0, pytest-asyncio
1.5.0, pytest-cov 7.1.0, types-PyYAML 6.0.12.20261122, pip-audit 2.10.1 and
hypothesis 6.170.17 — while the *runtime* ranges resolved differently (FastAPI
0.165 and bcrypt 5.0 on the clean environments, 0.118 and 4.x on the
development machine), which is the finding F-02 measures.

---

## 9. Findings

Findings are ordered by severity. Each states the evidence, the impact and the
recommended action.

### F-01 — HIGH — The frontend test suite covers 4.15 % of the HMI

The HMI contains 19 SCADA view components and the React hooks. The entire
frontend suite is **4 tests in 2 files**, and the measured coverage is 4.15 %
of lines, 5.95 % of functions and 0 % of branches. The enforced floor now
matches the measured value, so the gate protects against a regression, but it
protects almost nothing.

*Impact.* A regression in a view component is detected only by a human opening
the page. `AGENTS.md` §4 requires Playwright end-to-end tests; none are
configured.
*Action.* Add component tests for the views, then a Playwright suite for the
login → overview → setpoint path. Raise the floor as the suite grows.

### F-02 — HIGH — The Python runtime dependency ranges are not pinned

`backend/requirements.txt` declares every runtime dependency with `>=`.
Two builds of the same commit can resolve to different versions, and
`pip-audit` audits the *ranges* rather than one exact build.

The **CI toolchain** is now pinned to exact versions in
`backend/requirements-ci.txt`, so the linters, the type checker and the test
runner are the same in every run. The **runtime** dependencies are not.

*Impact.* A release is not byte-for-byte reproducible, and a newly published
upstream version can change a release build without a commit. The effect was
observed during this audit: the same source tree resolved to FastAPI 0.165 and
bcrypt 5.0 on a clean Python 3.12 environment, against 0.118 and 4.x on the
machine it had been developed on. The suite passed against both, which is
reassuring but is not the same as being pinned.
*Action.* Generate and commit a lock file with `pip-compile --generate-hashes`
and install with `pip install --require-hashes` in the release job.

### F-03 — MEDIUM — The ORM models are not compared against the migrations

The offline migration validation checks that the graph has exactly one head and
that the whole chain renders to SQL. It does **not** compare the ORM metadata
with the migration history, because that check requires a live database and a
non-empty `target_metadata`.

*Impact.* A model column that was added without a migration can reach a
release undetected.
*Action.* Add a `target_metadata` to `migrations/env.py` and run `alembic
check` against an ephemeral PostgreSQL service container in the release job.

### F-04 — MEDIUM — Branch protection of `main` is documented but not applied

`docs/CI_CD_GUIDE.md` §3 lists the exact required status checks, but the
branch-protection configuration is a property of the repository on GitHub and
is not part of the source code.

*Impact.* Until an administrator applies it, nothing technically prevents a
merge into `main` without a green build.
*Action.* An administrator applies the documented rule set. This is an
operations task, not a code change.

### F-05 — MEDIUM — Playwright end-to-end testing is not configured

`AGENTS.md` §4 names Playwright for frontend end-to-end tests. The repository
has Vitest unit tests only.

*Impact.* The full operator path — log in, read the overview, issue a
setpoint, observe the result — is never exercised automatically.
*Action.* Add a Playwright project with a mock API, once the frontend has a
stable test harness.

### F-06 — MEDIUM — Two mission items of `AGENTS.md` §1 are not implemented

The platform mission lists **digital-twin calibration and warranty analysis**.
Neither exists: there is no `calibration` package and no `warranty` package,
in `backend/app/` or in `plugins/`. Hardware-in-the-loop is explicitly a later,
separately approved phase, and market clearing and dispatch optimisation are
not implemented either — the platform has an energy-arbitrage plugin and a
scheduled-profile EMS mode, but no market model and no price formation.

*Impact.* The platform is a plant simulator with a control hierarchy, a
grid-service framework and a scenario framework, not an asset-lifecycle or
market simulator.
*Action.* Treat these as roadmap items. They must **not** be represented as
implemented in any status document.

### F-07 — MEDIUM — The workflow definitions have not been executed on GitHub

The six workflow files were corrected and reviewed, and their steps were run
locally, but no GitHub Actions run was observed.

*Impact.* A YAML or expression error in a workflow is invisible until the
pipeline runs.
*Action.* Open a pull request and let the pipeline run before the release
workflow is trusted with a real tag.

### F-08 — LOW — A module-level simulation entry point remains

`backend/app/api/v1/simulation_ctrl.py` keeps
`set_active_simulation_engine(...)` as a compatibility helper for the unit
tests. It writes to the application-scoped runtime under a lock, so it is not
an unguarded global, but it is a second way to reach the same state.

*Action.* Remove it once the tests construct their plant through the
application-scoped runtime directly.

### F-09 — LOW — The operator-action audit trail is not dedicated or tamper-evident

Commands, setpoints and faults reach the historian and the structured logs,
which satisfies `AGENTS.md` §2.10 for the simulated platform. There is no
separate, append-only operator-action journal.

*Action.* Add an append-only operator-action journal if the platform is ever
used for warranty or dispute resolution, which is the use case that motivates
`AGENTS.md` §1's warranty analysis.

### F-10 — LOW — Illustrative parameters are labelled in prose, not in the schema

`AGENTS.md` §2.14 requires illustrative parameters to be clearly labelled.
The reference topology and the plugin datasheets are labelled in the
documentation, but no schema field or test enforces it.

*Action.* Add an `illustrative: bool` marker to the equipment configuration
models, and a test that asserts every shipped example configuration is
marked.

### F-11 — LOW — The line length differs between two areas of the repository

`backend/` is formatted at 100 characters (`backend/pyproject.toml`) and
`scripts/`, `tests/` and `plugins/` at 88 (root `ruff.toml`). For the same
reason, `E501` is ignored for the 88-wide trees and stays active in
`backend/`: Ruff's formatter never reflows a docstring or a comment, so
enabling `E501` there would demand prose-only edits that the formatter itself
declines to make.

*Impact.* Cosmetic only. It was chosen deliberately: unifying on 100 would
reformat 41 files that the change has nothing to do with, which
`AGENTS.md` §7 forbids.
*Action.* Unify in a dedicated, separate change.

### F-12 — INFO — OPC UA and MQTT are interface specifications only

`backend/app/communication/adapter.py` defines the adapter contract, and the
Modbus TCP server implements it. No OPC UA or MQTT adapter exists.

*Action.* Keep them listed as `NOT IMPLEMENTED` until they are built.

---

## 10. Coverage of the Platform Mission (`AGENTS.md` §1)

| Mission item | Status | Notes |
| :--- | :--- | :--- |
| Complete internal BESS simulation | **IMPLEMENTED** | Deterministic tick engine, five-phase DAG, pause/resume/step/reset/replay |
| Battery model | **IMPLEMENTED** | Energy-balanced ECM, usable versus nominal capacity, auxiliary consumption |
| BMS model | **IMPLEMENTED** | Thresholds, alarm deduplication, persistent faults, contactor interlocks |
| PCS / inverter model | **IMPLEMENTED** | Four explicit P/Q stages, capability circle with priority, ramp limiters, thermal mass |
| Transformer model | **IMPLEMENTED** | `backend/app/models/bop/transformer.py` |
| Switchgear model | **IMPLEMENTED** | `backend/app/models/bop/switchgear.py` |
| Auxiliary model | **PARTIAL** | Auxiliary consumption is modelled inside the battery system; there is no standalone auxiliary package |
| Grid model | **IMPLEMENTED** | Grid state and disturbances, balanced three-phase power flow, interface stub for PandaPower/OpenDSS |
| Equipment controller (Layer A) | **IMPLEMENTED** | Start-up state machine with command verification and rollback |
| PPC (Layer B) | **IMPLEMENTED** | POI voltage and power-factor regulation, proportional allocation |
| EMS (Layer C) | **IMPLEMENTED** | Multi-container feasibility aggregation, droop, scheduled profile mode |
| POI simulation | **IMPLEMENTED** | `backend/app/models/grid/poi_model.py` |
| Grid-frequency simulation | **IMPLEMENTED** | Grid operating state and disturbance model |
| Grid services | **IMPLEMENTED** | Seven plugins in `plugins/grid_services/` — FCR, aFRR, MFRR, energy arbitrage, peak shaving, renewable smoothing and volt-var support — behind the `grid_service` interface, with a status model and SoC-based unavailability |
| Energy-market scenarios | **PARTIAL** | Energy-arbitrage scheduling, the EMS scheduled-profile mode and the scenario framework with fault injection and acceptance criteria are implemented. **Market clearing, price formation and dispatch optimisation are NOT IMPLEMENTED** |
| Vendor-specific equipment plugins | **IMPLEMENTED** | CATL, Tesla, SMA, Sungrow, behind a registry |
| Local web HMI | **IMPLEMENTED** | 19-view React + TypeScript SCADA, live telemetry, "SIMULATED DATA ONLY" labelling |
| Historian | **IMPLEMENTED** | Ring buffer with zero-silent-loss disk overflow, query API |
| Controller-in-the-loop (CIL) | **IMPLEMENTED** | Real isolated Modbus TCP gateway on loopback, register map, watchdog, setpoint routing |
| Hardware-in-the-loop (HIL) | **NOT IMPLEMENTED** | A later, separately approved phase, per `AGENTS.md` §2.2 |
| Digital-twin calibration | **NOT IMPLEMENTED** | See F-06 |
| Warranty analysis | **NOT IMPLEMENTED** | See F-06 |

---

## 11. Verdict and Recommended Actions

### 11.1 Verdict

The PowerTwin platform **passes** this audit as a simulation and emulation
platform. The safety-critical boundary is correctly placed and correctly
enforced: nothing in the repository can reach real equipment, and the
production configuration refuses to expose a writable interface on a
non-loopback address. The deterministic simulation core, the three-layer
control hierarchy and the plant topology engine are implemented, tested and
documented.

The audit does **not** find a defect that would make the platform unsafe to
operate in simulation. It finds an engineering-maturity gap in the delivery
chain: a thin frontend suite, unpinned Python **runtime** dependencies, a
missing ORM-versus-migration comparison, and workflows that have not yet been
executed on the CI provider.

The verification pass did, however, surface four delivery defects that were
invisible from the source alone — an inert pytest configuration, an inert
coverage configuration, an unpinned CI toolchain that also polluted the
runtime image, and a release-critical SBOM generator with no unit test that
did not type-check. All four are fixed. They are recorded in §8.1 because the
fact that they were possible is itself a finding: a configuration file that
looks authoritative while changing nothing is a trap for the next engineer.

### 11.2 Recommended actions, in order

1. **Run the pipelines on GitHub** (F-07). Open a pull request, let all six
   workflows run, and fix whatever the runner reports. Until this happens the
   delivery chain is verified by review and by local execution only.
2. **Pin the Python runtime dependencies with hashes** (F-02). The CI toolchain
   is pinned; the runtime dependencies are not. This is the single remaining
   change that most improves the reproducibility of a release.
3. **Close the migration-metadata gap** (F-03). Add `target_metadata` and an
   ephemeral PostgreSQL service to the release job, then restore
   `alembic check`.
4. **Build the frontend test suite** (F-01) and the Playwright end-to-end
   path (F-05), then raise the enforced floor as the suite grows.
5. **Apply the branch protection** (F-04). An administrator action, using the
   documented check names.
6. **Schedule the roadmap items** (F-06) explicitly, and keep them marked
   `NOT IMPLEMENTED` until they exist.
7. **Close the low-severity items** (F-08, F-09, F-10, F-11) as part of the
   next maintenance pass.

---

## 12. Audit Evidence Index

| Evidence | Where it lives |
| :--- | :--- |
| Non-negotiable safety rules | `AGENTS.md` §2 |
| Architecture, engineering, plugin and simulation rules | `AGENTS.md` §3–§6 |
| Lint rule set (pinned in the repository) | `ruff.toml`, `backend/pyproject.toml` |
| Test and coverage configuration (pinned in the repository) | `pytest.ini`, `.coveragerc` |
| Pinned CI toolchain | `backend/requirements-ci.txt` |
| Coverage policy (enforced) | `scripts/check_coverage.py`, `docs/CI_CD_GUIDE.md` §4 |
| Coverage policy (tests) | `tests/test_ci_scripts.py` |
| Migration validation | `scripts/validate_migrations.py` |
| Release version validation | `scripts/validate_release_version.py` |
| SBOM generation and its tests | `scripts/generate_sbom.py`, `tests/test_ci_scripts.py` |
| Determinism fingerprint | `scripts/endurance_campaign.py` |
| Requirement traceability | `docs/POWER_TWIN_REQUIREMENTS_TRACEABILITY.md` |
| Known limitations | `docs/POWER_TWIN_KNOWN_LIMITATIONS.md` |
| Implementation status | `docs/POWER_TWIN_IMPLEMENTATION_STATUS.md` |
| Pipeline architecture and operations | `docs/CI_CD_GUIDE.md` |
