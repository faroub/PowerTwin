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
thin frontend test suite, the missing ORM-versus-migration comparison, and the
fact that the `main` branch is not protected against a direct push. The
delivery pipeline itself is no longer among them: it has now been executed by
GitHub Actions and the run on the corrected files was green across every job.

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

1. **The green GitHub Actions run is now observed.** The six workflow files
   **have** been executed on a GitHub runner. The first run on the merged
   `main` branch exercised the whole pipeline against a commit carrying all of
   the remediation work: every backend, frontend, system-engineering,
   secret-scanning, dependency-audit and CodeQL job **passed**, and two jobs
   failed with real defects that were then reproduced locally, corrected and
   re-verified locally. The corrected files were subsequently merged into
   `main`, and the run on commit `9928aec` completed with **every job
   green**. The subsequent dependency-locking change, commit `4d69c20`, did
   the same across all twelve jobs, including the two new gates that check
   the installed environment against the lock. What a green run does *not*
   establish is that the gates cover
   every possible defect — the coverage gaps recorded as F-03, F-04 and
   F-11 are entirely unaffected by it. F-01, F-03, F-05, F-09 and F-11 have
   since been closed: the frontend component suite and the Playwright
   end-to-end path are enforced pipeline gates, the ORM-versus-migration
   drift gate runs in the release job, the platform has a dedicated
   tamper-evident operator-action journal, and the whole repository is linted
   with one declared style. F-04 remains, because branch protection is an
   administrator action on the repository configuration rather than a change
   to the code — although the rule set is now executable and verifiable
   through `scripts/apply_branch_protection.py`, so applying it is one
   command rather than a manual transcription of a checklist.
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
| 10 | All commands, setpoint changes, configuration changes, faults and operator actions audited | **COMPLIANT** | Every category flows through the dedicated operator-action journal (`backend/app/core/operator_journal.py`): an append-only, SHA-256 hash-chained JSON Lines trail that is always on, survives a restart, and reports the first break in its chain. Commands and setpoints through `ControlCommandLog`, configuration changes through `ConfigChangeAuditLog`, authentication events through `AuditLog`, faults through `FaultInjectionEngine`, operator actions through the simulation control endpoint — including the refused ones. Finding **F-09** is closed (C) |
| 11 | Never silently fall back between a real and a simulated device | **COMPLIANT** | The gateway has a single, explicit mode; there is no fallback path in `backend/app/communication/` (C) |
| 12 | Never expose writable control interfaces to an untrusted network | **COMPLIANT** | Production startup rejects a non-loopback `HOST`; Modbus writes are refused on a non-loopback gateway host; RBAC denies by default (C) |
| 13 | No manufacturer-accuracy claim without validation | **COMPLIANT** | No such claim is made in code or documentation; plugin data is labelled as public-datasheet-derived and illustrative (D) |
| 14 | Illustrative parameters clearly labelled | **COMPLIANT** | `illustrative: bool` on every topology configuration model, defaulting to `True` and refusing an under-labelled plant (`backend/app/topology/schema.py`); carried into the runtime `EquipmentMetadata.is_illustrative` by the plant factory; stated explicitly by both shipped example configurations and asserted by `tests/test_illustrative_parameters.py` (C) |

**Safety conclusion.** All fourteen rules are now fully met. The audit-trail
rule was the last partial one; it was a documentation and tooling gap, not a
hazard to real equipment, and it could not expose a physical system because
no physical system is reachable.

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
| No global mutable state | **COMPLIANT** | The simulation runtime is application-scoped with a lock, and the runtime is the single write path to the plant and the engine: a plant is attached with `SimulationRuntime.attach_plant` and detached with `SimulationRuntime.drop`. The module-level `set_active_simulation_engine` helpers that offered a second route to the same state were removed with finding **F-08** (C) |
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
| pytest backend tests, Playwright frontend end-to-end tests | **COMPLIANT** | Both are used. The frontend has a Vitest component suite (176 tests) and a Playwright end-to-end suite (8 specs) that drives the built HMI against a hermetic mock platform. Recorded as findings **F-01** and **F-05**, both now resolved (D) |
| Pinned dependencies, reproducible builds | **COMPLIANT** | The frontend lock file is pinned and `npm ci` is used. The **Python** runtime dependencies are pinned in `backend/requirements.lock` and installed with `--require-hashes`, so a build either reproduces the recorded artefact exactly or fails, and the container build asserts in strict mode that the image carries exactly the locked packages and nothing else. Finding **F-02** is resolved (D) |
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
| The release workflow ran `alembic check` | It needed a live database and a non-empty `target_metadata`, so it failed with an import error **before** the release could be built | `scripts/validate_migrations.py` — offline, deterministic, credential-free validation of the migration graph, **plus** the drift gate of F-03: `alembic upgrade head` and `alembic check` against an ephemeral service container |
| `backend/alembic.ini` used relative paths | The path resolved differently depending on the working directory | `%(here)s` interpolation and `path_separator = os` |
| The SBOM was not valid SPDX 2.3 and had no unique identifiers | The artefact was not a usable SBOM | A valid SPDX-2.3 document with unique `SPDXID`s, concluded and declared licenses, a unique document namespace and a `SOURCE_DATE_EPOCH`-pinned timestamp |
| The SBOM and the dependency inventories were not shipped with the release | The release had no dependency evidence | The SBOM, the Python inventory and the full transitive npm inventory are in the archive and covered by `SHA256SUMS` |
| `release_version` and `random_seed` were decorative inputs | An operator could trigger a release with an arbitrary string | Both are consumed: the version is validated before anything is built, and the seed drives the nightly endurance campaign |
| The frontend declared a 75 % coverage threshold against a measured 4.15 %, and the coverage provider was not installed | The gate could not run at all | The provider is installed, `coverage.all` counts untested files, and the enforced floor is **75 %** — a threshold the suite now actually meets at 98.02 % |
| `npm audit --audit-level=high` was permanently red (1 high, 3 critical) | The security job never passed | The toolchain was upgraded to vite 7 / vitest 4, which clears the esbuild → vite → vitest → tinypool advisory chain; the audit reports **0 vulnerabilities** |
| The lint configuration was resolved from **outside** the repository | The lint result depended on the machine: a developer's run and the CI runner's run could legitimately disagree | A root `ruff.toml` pins the rule set inside the repository |
| The pytest and the coverage configuration lived in `backend/pyproject.toml`, where neither tool ever read it | Both tools ran with their built-in defaults: `asyncio_mode = "auto"` was never applied and the coverage `source` was never applied, so the declared configuration was inert | `pytest.ini` and `.coveragerc` at the repository root, which is where the tools are actually invoked |
| The CI toolchain was unpinned, and the linters and the test runner were declared as *runtime* dependencies | The production image installed ruff, mypy and pytest, and a new upstream release could silently change the pipeline | The CI toolchain is pinned to exact versions in `backend/requirements-ci.txt`; `backend/requirements.txt` now carries runtime dependencies only |
| `scripts/generate_sbom.py` had no unit test and failed `mypy --strict` | A release-critical script was unverified, and the type-check gate was red | 13 unit tests, precise typing, and a shape-validating inventory loader that rejects a malformed inventory instead of silently producing an empty SBOM |
| A pull request was only tested when it targeted `main` | A feature branch was unverified until merge | `pull_request` fires for any branch |

### 8.2 The gates that now exist

| Gate | Mechanism | Failure mode |
| :--- | :--- | :--- |
| Formatting | `ruff format --check backend plugins tests scripts deployment` | Job fails |
| Linting | `ruff check backend plugins tests scripts deployment` with the rule set pinned in the repository | Job fails |
| Type checking | `mypy --config-file backend/pyproject.toml backend plugins scripts` (`strict = true`) | Job fails |
| Unit and integration tests | `pytest` with `-W "error::pytest.PytestUnraisableExceptionWarning"` | Job fails |
| Coverage policy | `python scripts/check_coverage.py coverage.json` | Job fails |
| Interpreter compatibility | Matrix on Python 3.13 and 3.14, `fail-fast: false` | Job fails |
| Frontend lint, test, build and coverage | `npm run lint`, `npm test`, `npm run build`, `npm run test:coverage` | Job fails |
| Frontend end-to-end path | `npm run test:e2e` (Playwright against the built artefact on the loopback interface, with a hermetic mock platform) | Job fails |
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

The two Ruff rows above record the scope and the line length that were in
force when the matrix was run. Both have since changed: the lint scope was
widened to include the `deployment/` tree, and the line length was unified at
100 characters across the whole repository (finding **F-11**). The unified
gate was re-executed locally afterwards — **176 files already formatted**,
**all checks passed** — and the current test count is **501 passed** against
the 315 recorded above.

The frontend gates were executed as well. At the time of the audit they were
`npm run lint` (TypeScript) clean, `npm test` 4 passed in 2 files,
`npm run test:coverage` satisfied the enforced floor at 4.15 % lines and 5.95 %
functions, `npm run build` produced the production bundle, and
`npm audit --audit-level=high` reported **0 vulnerabilities**.

**They have since been re-executed against the frontend component suite and
the Playwright project**: `npm run lint` clean over `src/`, `e2e/` and
`playwright.config.ts`; `npm test` **176 passed in 11 files**;
`npm run test:coverage` satisfied the enforced floors at **98.02 % lines,
99.21 % functions, 98.03 % statements and 88.02 % branches**;
`npm run test:e2e` **8 passed** against the built artefact on the loopback
interface with a hermetic mock platform; `npm run build` produced the
production bundle.

`pip-audit` was executed against the declared ranges **and** against the fully
resolved environment: **no known vulnerabilities** in either.

### 8.5 The container images, as built and as measured

The two container images that the pipeline builds were built locally with the
exact command the pipeline uses and were scanned with the exact Trivy version
the action installs (v0.70.0).

| Measurement | Before | After |
| :--- | :--- | :--- |
| Backend image size | 609 MB | **281 MB** |
| Backend image, CRITICAL findings | 0 | 0 |
| Backend image, HIGH findings with a published fix | 76 | **0** |
| Backend image, HIGH findings without a published fix | 82 | 53 (all inherited from the base image) |
| Frontend image, CRITICAL and HIGH findings | not scanned | **0** |

The backend image was rebuilt as a multi-stage image. The single-stage image
retained `build-essential` and `libpq-dev` in its runtime layer, which pulled
in `linux-libc-dev`, the Kerberos chain, the ncurses and Perl trees and the
whole GCC and binutils toolchain. The runtime layer now carries none of them,
runs `apt-get upgrade` so that the newest published distribution patches are
applied, and ships no package installer: the `pip` and `wheel` distributions
are removed from the virtual environment once the dependencies are in place,
and the base image's own `pip` is removed as well, so neither interpreter in
the image can install anything at run time.

The residual 53 high-severity findings are 13 advisory identifiers across 21
packages that the Debian trixie base image necessarily contains, and a scan of
the **unmodified** base image reports the identical identifiers. Debian has
published no fix for them, so no change to this repository can remove them.
They are enumerated, justified and bounded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.11.

The gate was therefore split by the party that owns each package family: the
operating-system scan fails on every advisory **that has a published fix**, so
the residual set cannot be ignored into permanence — the moment Debian
publishes a fix, the scan starts reporting it and the build fails until the
image picks the patch up; and the application-package scan accepts **no**
critical or high advisory at all, whether or not a fix exists, and is
unaffected by the inherited set. No ignore file is used anywhere.

The rebuilt image was additionally started and checked: it reports **healthy**
through its own health probe, answers `/health/readiness` with the
`SIMULATION_ONLY` safety invariant intact, and runs as the non-root user
uid 10001.

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
development machine). That divergence was the finding F-02 measured, and it
is now closed: the runtime dependencies are resolved once, into
`backend/requirements.lock`, and every job installs that lock with
`--require-hashes`, so all three interpreters now run against the same
versions.

---

## 9. Findings

Findings are ordered by severity. Each states the evidence, the impact and the
recommended action.

### F-01 — HIGH — RESOLVED — The frontend test suite covers 98.02 % of the HMI

The HMI contains 19 SCADA view components and the React hooks. The frontend
suite is now **176 tests in 11 files**, and the measured coverage is **98.02 %
of lines, 99.21 % of functions, 98.03 % of statements and 88.02 % of
branches**. The entry point, the shared components, the login flow, the
telemetry hook, the API client, the permission table and every SCADA view are
covered.

The enforced floors in `frontend/vite.config.ts` are **75 %** for every metric
globally, with tighter per-directory floors on the session modules, the shared
components and the views. The binding of the directory-scoped floors was
verified empirically: they were deliberately raised until the gate failed,
which confirmed that a view that loses its tests fails the gate even when the
global figure barely moves.

Two defects were found and fixed while writing the suite, rather than
asserted around: the telemetry hook cleared its loading flag as soon as the
request was issued, so the views reported "N/A" for a frame that was still in
flight; and the views rendered illustrative equipment parameters without the
label that `AGENTS.md` rule 14 requires, which the shared
`SimulatedDataNotice` now carries and the test table enforces per view.

*Residual limitation.* The suite exercises the HMI against a mocked backend,
so it proves the HMI's own behaviour and not the agreement with the live
FastAPI backend. Branch coverage at 88.02 % is the weakest metric.

### F-02 — HIGH — RESOLVED — The Python runtime dependencies are pinned and hash-verified

`backend/requirements.txt` declares every runtime dependency with `>=`. That
file is what a human maintains: it says which major version the project is
written against. The **resolution** of those declarations is
`backend/requirements.lock`, which was generated with `pip-compile
--generate-hashes` and commits, for all 35 packages including the transitive
ones, one exact version and the SHA-256 hash of every distribution of that
version.

The container image and every workflow install the lock with
`pip install --require-hashes`, so a build either reproduces the recorded
artefact exactly or fails. The lock was verified to install cleanly and to
pass the whole suite on **Python 3.12, 3.13 and 3.14**.

**The deployed image carries only the packages of the lock.** Python 3.12 no
longer installs `setuptools` into a fresh virtual environment and nothing in
the service needs it. The build tool used to install the dependencies is
removed again afterwards, together with the dependency it drags in — the wheel
builder requires `packaging`, and removing the builder alone leaves that
dependency in the environment. The base image's own `pip` is removed as well,
so the shipped image carries no package installer at all.

That is a claim, and it is checked rather than left to the reading of an
uninstall chain. `scripts/verify_locked_environment.py` compares the
distributions that are actually installed against the packages the lock pins.
The container build runs it in **strict** mode, in which the installed set
must be exactly the locked set, so an image carrying a package that no hash
covers **fails to build** instead of being published. The pipeline runs it in
the default mode, which asserts that the CI toolchain install did not quietly
replace a runtime package with another version — precisely the substitution a
range-based install would perform silently. The script uses the standard
library only, because it has to run inside the image, whose virtual
environment carries nothing but the packages of the lock.

The rebuilt image was measured to hold **exactly 35 packages**, one per lock
entry, and the container smoke test asserts that no interpreter in the running
image can find a package installer.

`pip-audit` now audits the lock rather than the declared ranges, so it reports
on the versions that are actually installed and shipped rather than on the
newest version each range would resolve to.

**The lock cannot drift.** `scripts/check_dependency_lock.py` compares the
lock against the declarations and reports a declared requirement that is
missing from the lock, a locked version that no longer satisfies its declared
range, a locked entry without a hash, a locked entry that no declared
requirement reaches, and a dependency edge that names a package the lock does
not contain. The pipeline runs it and the test suite exercises it.

*Residual.* The lock is a snapshot: a newly published upstream release enters
it only when somebody regenerates it, which is the intended behaviour but
means the lock ages until it is regenerated. It was resolved on Python 3.12
and is installed with `--require-hashes` on 3.12, 3.13 and 3.14; a package
that publishes no wheel for a future interpreter would be built from its
source distribution, which the hash check still enforces. The CI toolchain
remains pinned by exact version in `backend/requirements-ci.txt` without
hashes, which is acceptable because it is build tooling and never enters a
deployed artefact. The strict environment check covers the *installed set*; it
does not by itself prove that every artefact in the lock came from the
upstream publisher, because a hash proves integrity rather than provenance.

### F-03 — MEDIUM — RESOLVED — The ORM models are compared against the migrations

The offline migration validation checked that the graph has exactly one head and
that the whole chain renders to SQL. It did **not** compare the ORM metadata
with the migration history, because that check requires a live database and a
non-empty `target_metadata`.

*Impact.* A model column that was added without a migration could reach a
release undetected.
*Action.* Add a `target_metadata` to `migrations/env.py` and run `alembic
check` against an ephemeral PostgreSQL service container in the release job.

**Resolution.** `backend/migrations/env.py` sets `target_metadata =
Base.metadata` and passes an `include_object` hook to Alembic that excludes
`telemetry_data_timestamp_ns_idx`, the index TimescaleDB creates itself when
the migration converts `telemetry_data` into a hypertable. The release job
declares a digest-pinned `timescale/timescaledb` service container and runs
`alembic upgrade head` followed by `alembic check`, so the schema the
migrations describe is built and then compared with the schema the ORM
declares.

Making that comparison clean exposed a real drift that the offline validator
had never been able to see: the ORM declared six individual column indexes on
`command_records` and `alarms_and_events` that no migration creates, and it
omitted the two composite indexes the migrations do create. The ORM was
corrected to declare exactly the deployed index set — `idx_cmd_target` on
`command_records` and `idx_users_username` on `users` — **without a schema
migration**, so the deployed database is untouched and no data is migrated.
The change is metadata only.

Two limits of the gate remain and are recorded in `docs/POWER_TWIN_KNOWN_LIMITATIONS.md`
§4.4: Alembic's autogenerate does not compare **primary keys**, and the gate
runs at release time rather than on every pull request.

`tests/test_deployment_images.py` asserts that the environment declares the
metadata, that the TimescaleDB-owned index is excluded, that the ORM and the
migrations declare the same index set, and that the release job runs the gate
against a database whose credentials agree with the service container's.

### F-04 — MEDIUM — Branch protection of `main` is not applied, but the rule set is now executable and verifiable

`docs/CI_CD_GUIDE.md` §3 lists the exact required status checks, but the
branch-protection configuration is a property of the repository on GitHub and
is not part of the source code.

*Impact.* Until an administrator applies it, nothing technically prevents a
merge into `main` without a green build.
*Action.* An administrator applies the documented rule set. This is an
operations task, not a code change.

**Partial progress — the action is now executable.** A prose checklist is not
a control: it goes stale the moment a job is renamed, and it cannot be
verified. `scripts/apply_branch_protection.py` turns the checklist into an
action:

- the required status checks are declared **once**, in the script;
- the payload is built from that declaration and can be printed without
  touching the network (`--dry-run`), so an administrator can see exactly
  what would be sent before sending it;
- after the rule is applied it is **read back** from GitHub and compared
  against the declaration, and the script exits non-zero if what is in force
  is looser than what was documented — a missing check, a missing approval,
  an administrator who can bypass the rule, a permitted force push or a
  permitted deletion all count as a failure.

Three tests in `tests/test_ci_scripts.py` hold the three sources together:
the check names in the §3 table, the declaration in the script, and the
`name:` of every job in `.github/workflows/`. A check renamed in a workflow,
or a row added to the table without a matching job, fails the suite instead
of silently blocking every merge on the branch. Each of the three was probed
by breaking the source it guards, so a test that cannot fail proves nothing.

**A partial application is now reported instead of raising.** The rule set is
applied in two requests — the main `PUT` that carries the status checks, the
review requirement and the push restrictions, and the `POST` that carries the
signed-commit requirement. GitHub answers the second one with **HTTP 422**
while *Commit signature verification* is off in the repository settings. The
script used to raise on that response **before** its verification, so an
administrator was left with an exception and no way to tell whether the eight
required checks, the approving-review requirement and the linear-history
requirement were now in force. They usually were: the `PUT` had already
succeeded.

The script now captures that failure, still performs the read-back, and
reports both halves — every property that **is** in force, and a `WARNING:`
line naming the repository setting to enable. The exit code stays non-zero,
because a signed-commit requirement that could not be confirmed is not a rule
that can be called verified. The failure of the main `PUT` is still raised,
because in that case nothing was applied and there is nothing to report.
Four further tests in `tests/test_ci_scripts.py` cover the four paths: a
failed signed-commit request, a failed signed-commit read-back, a failed main
request, and the command-line exit status.

**The finding remains open.** The rule is still not applied, and applying it
requires a token with `administration` permission on the repository, which
this work has no way to obtain. What could be verified from outside the
repository was verified: the repository's **rulesets list is empty**
(`GET /repos/faroub/PowerTwin/rulesets` returns `[]`), and the legacy
branch-protection endpoint answers `401 Requires authentication`, so the
legacy setting could not be read anonymously either. The absence of a ruleset
is therefore a verified fact; the absence of a legacy branch-protection rule
is not, because reading it needs a token. **An administrator must run the
script and confirm its exit status.**

### F-05 — MEDIUM — RESOLVED — The Playwright end-to-end path is configured and runs in the pipeline

`AGENTS.md` §4 names Playwright for frontend end-to-end tests. A Playwright
project now exists: `frontend/playwright.config.ts` and seven specs in
`frontend/e2e/`, driving the **built** HMI in Chromium against a **hermetic
mock platform**.

The mock answers every `/api/v1/**` request inside the browser, **aborts**
any path it does not model, and **blocks** any request to a host other than
the local preview server on `127.0.0.1`. The specs assert that neither an
unmodelled path nor a blocked host occurred, so the suite cannot quietly come
to depend on an endpoint nobody modelled or on a network that should not
exist. The specs cover the operator path — log in, read the overview, pause
the engine behind its confirmation, observe the result, log out — and the
safety posture: the session token travels in memory and in the `Authorization`
header only, never in `localStorage`, `sessionStorage` or a cookie; a backend
that is not ready is reported as disconnected rather than replaced by
invented figures; a refused control action is reported as a failure without
the engine state being set to a successful one.

The suite runs in the `Frontend Lint, Test & Build` pipeline job, after
`npx playwright install --with-deps chromium`. `frontend/tsconfig.json`
includes `e2e/` and `playwright.config.ts`, so the end-to-end code is
type-checked by the same gate as the application, and
`tests/test_deployment_images.py` asserts the properties of the configuration
so that the gate cannot be silently removed.

*Residual limitation.* The suite runs against a mock, not against the live
backend, and covers Chromium only.

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

### F-07 — MEDIUM — RESOLVED — The workflow definitions have now run on GitHub, two defects were found, and the next run was green

The six workflow files **have now been executed by GitHub Actions**. The
first run on the merged `main` branch was the first one that exercised the
whole pipeline against a commit carrying all of the remediation work. Every
backend, frontend, system-engineering, secret-scanning, dependency-audit
and CodeQL job **passed**. Two jobs failed, and both failures were real
defects rather than flakes:

1. **The compose validation failed.** `docker-compose.yml` declares
   `POSTGRES_PASSWORD` as mandatory with the `${POSTGRES_PASSWORD:?...}` form,
   but the pipeline step that renders the compose file did not supply one. The
   step aborted with exit code 15 and *required variable POSTGRES_PASSWORD is
   missing a value*. The requirement itself was correct; the step was
   corrected to supply a validation-only placeholder, and the requirement was
   left untouched.
2. **The container scan failed.** The backend image was built as a single
   stage that retained the compiler toolchain, and the scan reported 158
   high-severity operating-system findings. The image was rebuilt as a
   multi-stage image with no build toolchain in the runtime layer, which
   removed 105 of them, and the scan policy was split into two families so
   that the residual inherited advisories — which Debian has not yet fixed
   and which no change to this repository can address — do not make the gate
   unsatisfiable.

Both defects were reproduced locally before anything was changed, and both
were fixed and re-verified locally: the compose file renders with the
placeholder and still refuses to render without one; the rebuilt image passes
both scan policies with **zero** fixable findings, starts, reports healthy
through its own health probe and upholds the safety invariants.

*Resolution.* The corrections were merged into `main` and pushed. GitHub
Actions executed the corrected workflow files themselves on commit `9928aec`,
and **every job completed successfully**: the infrastructure and Docker build
validation, the backend unit and integration tests, the backend lint and
typecheck, the backend test matrix on Python 3.13 and 3.14, the system
engineering and physics validation, the frontend lint/test/build, the final CI
summary, the Trivy container scan, the Python and npm dependency audit, the
secret and credential scan, and CodeQL. The same result was reproduced on
the dependency-locking change, commit `4d69c20`, which added two further
gates and still completed with all twelve jobs green.

*Residual.* A green run means that no gate failed; it does not mean that the
gates cover every possible defect. The coverage gaps that remain are recorded
separately as F-03, F-04 and F-11, and none of them is closed by this run.
F-01, F-03, F-05, F-09 and F-11 have since been closed by the frontend
component suite, the ORM-versus-migration drift gate, the Playwright
end-to-end path, the dedicated operator-action journal and the unification of
the lint style. F-04 remains open: branch protection is applied in the
repository configuration by an administrator, not by a change to the code.

### F-08 — LOW — RESOLVED — The runtime is the single write path to the plant and the engine

`backend/app/api/v1/simulation_ctrl.py` kept
`set_active_simulation_engine(...)` as a compatibility helper for the unit
tests. It writes to the application-scoped runtime under a lock, so it is not
an unguarded global, but it is a second way to reach the same state. A second
copy of the same helper also existed in `backend/app/simulation/runtime.py`.

*Action.* Remove it once the tests construct their plant through the
application-scoped runtime directly.

**Resolution.** Both copies of the helper are gone. The runtime's own methods
are now the only way in:

- `SimulationRuntime.attach_plant(plant)` attaches the plant, its engine and a
  runner, and stops any runner that was still attached.
- `SimulationRuntime.drop()` detaches them and stops the runner thread.

The tests now construct their plant through the runtime
(`get_simulation_runtime(app=client.app).attach_plant(plant)`), which is the
route the API itself resolves, so a test exercises the same path the
application does.

Two defects disappeared with the helper rather than with it. The API-module
copy detached the plant **without stopping the runner thread**, so a
detached runtime could leave a live execution thread behind; `drop()` stops
the runner. And the integration test attached its plant to the app-scoped
runtime but detached it from the module fall-back runtime, so the teardown
never actually ran; both ends now address the same runtime.

The read-only accessors `get_active_simulation_engine` and `get_active_plant`
remain: they observe the runtime and do not offer a second way to change it.
`tests/test_simulation_runtime.py` asserts that neither module exposes
`set_active_simulation_engine` again, and that the runtime never holds an
engine without its plant or the other way round.

### F-09 — LOW — RESOLVED — The operator-action audit trail is dedicated and tamper-evident

The audit trail was spread over four mechanisms that did not agree with each
other: `backend/app/core/audit.py` kept authentication events in memory and
flushed them to a JSON file inside the source tree, `backend/app/core/config_audit.py`
kept configuration changes in memory only, `backend/app/controllers/command_log.py`
kept commands and setpoint changes in memory only in a separate instance per
control layer, and `backend/app/historian/service.py` owned the durable
`command_records` table that nothing in the running application ever wrote to.
The operator's primary control surface — `POST /api/v1/simulation/control`,
which starts, pauses, steps and resets the plant — recorded **nothing at
all**. The historian's `record_alarm()` had no callers either. The audit
finding's premise that commands, setpoints and faults "reach the historian"
was therefore inaccurate: they reached an in-memory buffer.

*Action.* Add an append-only operator-action journal if the platform is ever
used for warranty or dispute resolution, which is the use case that motivates
`AGENTS.md` §1's warranty analysis.

**Resolution.** The platform now has one dedicated, append-only,
tamper-evident journal, and every category that `AGENTS.md` §2.10 names flows
through it.

- `backend/app/core/operator_journal.py` is the journal. It is a JSON Lines
  file that is only ever opened in append mode: no method rewrites,
  truncates or deletes an entry.
- It is **hash-chained**. Every entry carries the SHA-256 hash of its
  predecessor and the SHA-256 hash of its own canonical content. Changing,
  removing or reordering an entry breaks the chain from that point on, and
  `OperatorActionJournal.verify()` reports the first break.
- The chain **continues across a restart**: the last persisted entry is read
  back so that the next entry follows it, rather than a second parallel chain
  starting in the same file.
- It is **process-scoped**: one guarded service, one trail. Two applications
  in one process cannot write two trails that both claim to be complete.
- It is **always on**. `AGENTS.md` §2.10 requires the record, so there is
  deliberately no setting that turns it off; `OPERATOR_JOURNAL_PATH` and
  `OPERATOR_JOURNAL_FSYNC` are the only knobs, and `fsync` defaults to on.
- Sensitive values in the details are redacted with the existing
  `redact_details`, so the journal never becomes a second store of
  credentials.

All five required categories now reach it: commands and setpoint changes
through `ControlCommandLog`, configuration changes through
`ConfigChangeAuditLog`, authentication events through `AuditLog`, faults
through `FaultInjectionEngine`, and the operator's own actions through the
simulation control endpoint — including the actions that were **refused**,
because a trail that only records what succeeded cannot show what was
attempted.

`tests/test_operator_journal.py` (29 tests) covers the properties a warranty
or dispute analysis relies on: the entry is read back unchanged, the chain
links every entry to its predecessor, an altered, removed, reordered or
truncated entry is detected, the chain survives a restart, a failed write is
reported as a typed error and logged rather than swallowed, and each of the
five categories really reaches the journal. Each test was probed by breaking
the behaviour it guards, so a test that cannot fail proves nothing.

**A second defect surfaced on the way.** The journal's promise that "the
error is never swallowed" is void if the logger itself has been switched off,
and it had been: `backend/migrations/env.py` called `logging.config.fileConfig`
with its default `disable_existing_loggers=True`, which disables **every**
logger that already exists in the process. The migration tooling imports that
environment inside the process that owns the audit trail, so running the
migration graph validation silenced the whole application log — the audit
trail included — without a word. The call now passes
`disable_existing_loggers=False`, and
`tests/test_ci_scripts.py::test_the_migration_environment_leaves_the_application_loggers_alone`
fails if it ever regresses.

*Residual limitation.* A journal write that fails is **fail-open**: the
error is logged, the journal marks itself degraded, and the action is *not*
rolled back. This is deliberate — a simulation action cannot be rolled back,
and failing closed would make the whole plant uncontrollable the moment the
disk fills — but it means a degraded journal has a gap in its trail. The
degraded flag and the last error are exposed on the journal for that reason.
It is recorded in `docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.9.

### F-10 — LOW — RESOLVED — The illustrative parameters carry a schema marker and a test

`AGENTS.md` §2.14 requires illustrative parameters to be clearly labelled.
The reference topology and the plugin datasheets were labelled in the
documentation, but no schema field or test enforced it.

The label is now part of the schema. `backend/app/topology/schema.py` defines
`IllustrativeConfigModel`, which every equipment configuration model and the
root `PlantTopologyConfig` inherit. Each carries an `illustrative: bool` field
that **defaults to `True`**, so a parameter set that forgets to state its
status is labelled rather than silently unlabelled: under-labelling is the
dangerous direction.

The plant-level marker follows the items. `PlantTopologyConfig` derives it
from the equipment markers when the author did not state it, and it **refuses
a configuration that claims to be validated while one of its items is
illustrative** — the contradiction that would under-label a plant is rejected
at parse time rather than accepted and forgotten.

The marker travels into the runtime. The plant factory passes it to every
equipment it builds, so the `EquipmentMetadata.is_illustrative` of the
batteries, the BMS units, the PCS units, the transformers, the switchgear,
the meters, the POI and the grid model reports the label the configuration
gave it. The historian already persists that field.

Both shipped example configurations now state the marker explicitly on the
plant and on every one of their items, and `tests/test_illustrative_parameters.py`
(12 tests) asserts that they do, that the default labels, that the plant-level
marker is derived and reconciled, and that the factory carries the marker into
the runtime equipment.

*Residual limitation.* The HMI has no topology-configuration API yet, so the
marker is not shown to the operator on screen. The label reaches the
configuration file, the runtime equipment metadata, the historian and the
build log; presenting it in the HMI is recorded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.10.

### F-11 — LOW — RESOLVED — The repository is linted with one declared style

`backend/` was formatted at 100 characters (`backend/pyproject.toml`) and
`scripts/`, `tests/` and `plugins/` at 88 (root `ruff.toml`). For the same
reason, `E501` was ignored for the 88-wide trees and stayed active in
`backend/`: Ruff's formatter never reflows a docstring or a comment, so
enabling `E501` there would demand prose-only edits that the formatter itself
declines to make.

*Impact.* Cosmetic only. It was chosen deliberately: unifying on 100 would
reformat 41 files that the change has nothing to do with, which
`AGENTS.md` §7 forbids.
*Action.* Unify in a dedicated, separate change.

**Resolution.** The two declarations now describe **one** style, and the
unification was made in its own change, as the action required.

- The line length is **100 characters in every tree**. Unifying upwards was
  the cheaper direction: the backend tree already satisfied it, while the
  other trees held exactly **one** line above 100 against 469 lines above 88.
- `E501` is now **active in both trees**. The one prose line that exceeded
  the limit was shortened by hand, because the formatter would not shorten it.
- The `deployment/` tree — the container health check — was **not linted at
  all**. It now has a pinned configuration like every other tree, and the
  pipeline lints it.
- The two files cannot be merged into one, because Ruff discovers its
  configuration by walking **up** the directory tree and
  `backend/pyproject.toml` is not an ancestor of `scripts/` or `tests/`. They
  are therefore kept in step by a test instead.

`tests/test_tool_configuration.py` (13 tests) makes the divergence
unrepeatable. It fails when the two declarations disagree on the line length,
the target version, the rule selection or the ignored rules; when `E501` is
disabled in either; when a Python tree appears that the declared set does not
cover; and when the pipeline stops linting one of the repository's trees. The
test reads the pipeline invocation out of the workflow rather than assuming
it, so it follows the pipeline when the pipeline changes.

### F-12 — INFO — OPC UA and MQTT are interface specifications only

`backend/app/communication/adapter.py` defines the adapter contract, and the
Modbus TCP server implements it. No OPC UA or MQTT adapter exists.

*Action.* Keep them listed as `NOT IMPLEMENTED` until they are built.

### F-13 — LOW — RESOLVED — The system info endpoint reported an engine the application did not own

`GET /api/v1/info` is where the HMI takes the engine state it shows the
operator. It read that state through `backend/app/simulation/engine_stub.py`,
which called `get_active_simulation_engine()` **without an application
handle**. That call resolves the module-level fall-back runtime — the
instance that exists for callers without an application handle — and not the
application-scoped runtime that holds the plant. The application and the
fall-back are distinct objects: `init_simulation(app)` constructs a runtime
for the application and binds it to `app.state`.

*Action.* Resolve the engine status from the application-scoped runtime, the
same source the Plant Overview reads.

**Resolution.** The endpoint resolves the runtime from the request
(`get_simulation_runtime(request=request)`) and reports `runtime.status()`,
exactly as `GET /api/v1/overview` does. The second implementation of the
engine status — which also computed `is_running` from the engine state
rather than from the runner — is removed with `engine_stub.py`, so the two
endpoints can no longer drift apart.

The defect was reproduced before it was fixed: with a plant attached and the
engine running, `/api/v1/info` answered `NOT_CONNECTED` while the runtime
reported `RUNNING`. The regression test
`tests/test_startup.py::test_system_info_reports_the_engine_that_owns_the_plant`
asserts that both endpoints describe the same engine and fails against the
unrepaired code with `assert 'NOT_CONNECTED' == 'RUNNING'`.

Two supporting defects disappeared with it. The runtime docstrings claimed
that start-up binds the module fall-back to the application — it does not,
and never did — and the test that asserted that claim did so with a
tautology (`runtime is default_runtime or runtime is not default_runtime`),
which could never fail. The docstrings now describe the actual binding, and
the test now asserts that the application's runtime is a distinct object
from the fall-back and that start-up leaves the fall-back untouched.

The endpoint remains **read-only and unauthenticated**: it exposes the
project metadata, the safety report and the engine state, and no control
surface and no credential. The telemetry and control endpoints remain behind
the bearer-token guard.

### F-14 — MEDIUM — RESOLVED — The speed factor had no upper bound, and the screen could not set it

Two defects sat behind the same operator-facing gap.

**The bound was missing.** `docs/04_SIMULATION_ENGINE_SPECIFICATION.md`
documents the speed factor as running from $0.1\times$ to $100\times$, with
`0.0` reserved for maximum headless execution speed. The implementation
enforced **neither** end: `SimulationConfiguration` accepted any float, and
so did `SimulationRunner.set_speed_factor` and
`SimulationRunManager.set_speed_factor`. A factor of `1e9` was accepted at
every boundary. That is a command the platform cannot execute meaningfully —
the pacing target becomes shorter than the time it takes to execute a tick,
so the simulation degenerates into an unbounded CPU load while the operator
believes the clock is being paced. `AGENTS.md` §2.8 and §2.9 require that
out-of-range commands are refused and that safe command limits are applied at
every relevant boundary.

**The screen could not reach it.** `SET_SPEED` was implemented in the control
endpoint and had no representation in the HMI. The Simulation Control card
that purported to report the factor showed a hard-coded `1.0 x` that was not
read from the engine and could not be changed from the screen.

*Action.* Put the bound in one place and apply it at every boundary; wire
the factor to the screen, and report the factor in force rather than the one
the screen was built with.

**Resolution.** The bounds live in `backend/app/simulation/config.py` as
`MIN_SPEED_FACTOR` (0.0) and `MAX_SPEED_FACTOR` (100.0), and the single
`validate_speed_factor()` function is the only place that decides whether a
factor is acceptable. It is applied at all four boundaries that accept one:
the configuration model, the engine, the runner and the control endpoint. The
control endpoint refuses an out-of-range factor with HTTP 400 and records the
refusal in the operator-action journal as `REJECTED` / `INVALID_SPEED_FACTOR`;
it does not correct the factor to a different one, because a silent
substitution would leave the operator believing the clock is paced the way
they asked.

The engine status now carries the factor **in force** — the one the clock is
actually paced with — so the screen cannot display a value that is not in
effect. The HMI reads it, shows it, and sets it through a **Wall-Clock
Pacing** card: the screen refuses an out-of-range factor without sending it
and names the requested factor in the confirmation modal.

Three tests carry the change. `test_a_speed_factor_outside_the_permitted_range_is_refused`
and `test_a_speed_factor_inside_the_permitted_range_is_accepted` pin the
endpoint's behaviour and assert that a refused factor leaves the factor in
force untouched;
`test_the_engine_and_the_runner_refuse_a_factor_the_api_refuses` asserts that
the engine, the runner and the configuration model refuse exactly what the
endpoint refuses, so a factor cannot walk around the bound. On the frontend,
`refuses a speed factor outside the permitted range without sending it` and
`dispatches a speed factor the operator asks for` cover the screen, and
`Operator path › sets the wall-clock speed factor from the screen` covers the
built artefact.

`0.0` remains a valid request and is not treated as a missing value: it is
the documented "run as fast as the host allows" setting. The screen labels it
`MAX (unpaced)` so that it cannot be mistaken for a stopped engine.

---

### F-15 — HIGH — RESOLVED — The historian is never written to by the running platform

`AGENTS.md` §1 requires a local web HMI **and a historian**. The historian
subsystem is implemented: `backend/app/historian/service.py` provides a
`HistorianService` with a ring buffer, a zero-silent-loss disk overflow, a
database flush and a replay path, and `backend/app/historian/query.py` reads
the tables it writes. The subsystem is also well tested — `tests/test_historian_db.py`
covers the buffering, the overflow and the flush.

**The running platform never instantiates it.** `HistorianService` is
constructed only in the test suite; no module in `backend/app/` calls
`record_telemetry`, `record_command` or `record_alarm`, and nothing calls
`flush_buffer_to_db` or `flush_all_to_db`. The tables `telemetry_data`,
`command_records` and `alarms_and_events` therefore stay empty in a
deployment, and the three read-only query endpoints answer with zero rows
against a store that was never fed.

Two places made this harder to see than it should have been. The HMI's
Historian screen printed *"Sampling: 100ms | Range: Last 1 Hour | Database:
PostgreSQL / TimescaleDB"* without issuing a single query, so the screen
asserted a working time-series store. And `backend/app/services/stubs.py`
contained a `get_service_health_stub()` that reported
`"historian_service": "READY"` for a service that was never created — a
placeholder that appeared operational, which `AGENTS.md` §4 forbids. The stub
was referenced by nothing and has been removed.

*Action.* Connect the historian to the running simulation so that the store
is fed, and make the screen's claim follow the store rather than precede it.

**Resolution.** The screen side of this finding was closed with F-16: the
HMI issues the queries and reports exactly what the store holds, including
"the store holds no rows". The platform side is now closed as well. The
change was approved under `AGENTS.md` §7.5 as **"recorder in the app
layer"**, and it was built on that footing.

The write path is `backend/app/historian/recorder.py`. `HistorianRecorder`
is a `SimulationTask` that lives in the **application layer** and registers
itself on the scheduler at phase 6 with a decimation interval
(`HISTORIAN_SAMPLE_INTERVAL_TICKS`, default 10 ticks). It samples the plant's
published states and writes only into the historian's in-memory queues. The
**simulation engine holds no database dependency**: a test asserts by AST scan
that the `backend/app/simulation` package imports neither `backend.app.historian`
nor `sqlalchemy` nor `asyncpg`, which keeps `AGENTS.md` §3 intact.

Every row carries the simulation timestamp, the run identifier, the quality
flag and `source_type="SIMULATED"`, so the recorded series stays faithful to
the run it belongs to. The recorder is **decimated but deterministic**: the
same run with and without the recorder attached produces the same engine
state, because the recorder observes and never participates in the physics.

Commands reach the historian through the platform's **single write path**.
The recorder does not wrap or re-implement `ControlCommandLog.log_entry`;
the command log gained a `add_sink` / `remove_sink` mechanism, and the
recorder subscribes to it. A command is therefore written to the hash-chained
operator journal and to the historian by the same call, and a rejected
command keeps its rejection reason in both.

The failure mode is safe by construction. `record_telemetry`,
`record_command` and `record_alarm` never block: they use
`queue.put_nowait` and spill to the documented disk overflow file when the
buffer is full. A database outage therefore cannot stall a tick. When the
commit fails, `flush_buffer_to_db` rolls back and writes every row to the
overflow file rather than dropping it, so no row is silently lost. The
overflow log names the real cause: *"memory buffer full"* is an application
capacity problem, *"database commit failed"* is an infrastructure problem,
and the two are distinguishable in the log.

The wiring is idempotent. Re-attaching the recorder — after a plant rebuild,
say — detaches the previous one first, so two recorders never write to the
same store and the scheduler never sees a duplicate task name. The recorder
can be switched off with `HISTORIAN_ENABLED=false`, and the application
still starts and serves.

`tests/test_historian_recorder.py` (22 tests) and
`tests/test_historian_wiring.py` (16 tests) cover the write path, including
the determinism property, the command subscription, the disk overflow, the
failed flush and the "one broken model does not cost the plant its sample"
rule. The backend suite grew from 540 to 552 tests.

The historian's mission coverage is therefore **IMPLEMENTED**. The store is
fed by the running platform, the read path is live, and a query returns what
the run recorded.

### F-16 — MEDIUM — RESOLVED — The HMI displayed values the platform never produced

Three screens showed figures that no backend had produced.

**The Historian screen** named a time-series store it never queried. The
backend has carried read-only endpoints for telemetry, the command audit log
and the alarm log since the historian was built; the screen issued none of
them and showed a fixed line of text instead.

**The Warranty screen** showed *Total Energy Throughput 124.5 MWh*,
*Equivalent Full Cycles 6.2 EFC* and *Current State of Health 100.0 % SOH*.
The backend has an endpoint, `/api/v1/historian/warranty/{container_id}`,
that returns the metrics the historian holds for a container — including
`total_energy_throughput_wh`, `equivalent_full_cycles`, `current_soh_pct`,
`max_temperature_recorded_c` and `time_above_45c_seconds`. The screen
ignored it and printed constants that looked exactly like measurements of a
battery.

**The System Settings screen** printed four safety invariants — *Application
Mode: SIMULATION ONLY*, *Hardware Integration: DISABLED*, *External Modbus
Writes: DISABLED*, *Automatic Device Discovery: DISABLED* — as text on the
screen, while the platform publishes the same posture under `safety` in
`/api/v1/info`.

*Action.* Read the platform instead of asserting on its behalf, and make
every screen distinguish an answer the platform gave from a value the screen
invented.

**Resolution.** The three screens now read the platform.

The Historian screen runs the three queries the endpoints offer and renders
the rows they return. It reports the three states apart from one another: the
store answered with rows, the store answered with none, or the query failed.
Those are different statements about the platform, and a screen that
collapsed them would tell an operator that a store which could not be reached
holds no history.

The Warranty screen asks for a container and shows the recorded metrics. When
the backend holds no record for that container it says so, and it says *why*:
the platform computes no degradation or warranty metrics on its own, and a
container appears only once a recorder has written its metrics. The
constants are gone; the screen no longer falls back to a plausible figure.

The System Settings screen reads the invariants from `/api/v1/info`. When the
platform does not answer, the invariants read `UNVERIFIED` rather than
`DISABLED`: an unreachable platform is not a disabled invariant, and the
screen has no evidence of the running state in that case. The row for the
simulation-only mode is labelled *Simulation-Only Mode* so that
`ENABLED` cannot be misread as "simulation is enabled" or as "the
simulation-only guardrail is off".

The frontend suite grew from 156 to 176 tests with this work and the
coverage that followed it, and the frontend coverage rose from 97.49 % to
**98.02 % of lines**, 99.21 % of functions, 98.03 % of statements and 88.02 %
of branches.

### F-17 — MEDIUM — RESOLVED — The historian endpoints failed unclearly, and had no API-level tests

The four historian endpoints had no API-level test at all: `tests/` covered
the historian's *service* and its *storage*, but nothing exercised the
endpoints that the HMI now depends on.

Their failure behaviour was also wrong. When the store was unreachable the
operator received a bare `500 Internal Server Error` with no explanation.
Catching `SQLAlchemyError` alone was not enough: the asyncpg driver lets the
underlying socket error escape untranslated when the host name cannot be
resolved, so a store that was simply not there arrived as `socket.gaierror`
and still produced a bare 500. A screen cannot tell "the store holds no
rows" from "the store could not be asked" when both arrive as a 500.

*Action.* Report an unreachable store as an explicit, explained failure, and
test the endpoints at the API level.

**Resolution.** `backend/app/api/v1/historian.py` routes every query through
a `_run_query` wrapper that catches both `SQLAlchemyError` and `OSError`,
logs the failure and answers **503** with
`"The historian store is unavailable; the query could not be answered."`. The
missing-record case remains a 404 with the container named, because a
container the store knows nothing about is a true statement and not a
failure.

`tests/test_historian_api.py` adds eight API-level tests over a stubbed
session: the endpoints reject an unauthenticated request, an observer can
read them, an empty store answers with no rows, an unreachable store answers
503, a store whose host cannot be resolved answers 503, a reversed time range
is refused, and the warranty endpoint answers with the recorded metrics or
404 for a container it knows nothing about.

The behaviour was confirmed against a running server: with the historian's
database absent, all four endpoints answer
`{"detail":"The historian store is unavailable; the query could not be answered."}`
with status 503.

### F-18 — LOW — RESOLVED — An unreachable HMI view fabricated the active configuration

`frontend/src/views/ConfigurationView.tsx` was a twentieth view component that
the application could not reach. It was absent from the `ViewId` union in
`frontend/src/components/Sidebar.tsx`, absent from the navigation entries,
and absent from the `renderView()` switch in `frontend/src/App.tsx`. No
operator could open it.

What it displayed was also a fabrication: a card headed **Active
Configuration** with the value `configs/dev.yaml`. That file is a development
*template* — project name, environment, safety flags, a database block and
simulation defaults — and no running plant loads it. The plant that runs is
built from `configs/reference_10mw_20mwh.yaml` or from the topology named by
`TOPOLOGY_CONFIG_PATH`, neither of which the view could have named. The
screen therefore presented a template as the configuration of a live plant.

*Action.* Remove a screen no operator can open, or give it a real source.

**Resolution.** The component and its test entry are removed. The platform
still has no endpoint that publishes the active topology, so a Plant
Configuration screen remains a **roadmap item**; it needs a read-only
endpoint, which is an external-interface change and therefore needs approval
under `AGENTS.md` §7.5. The count of reachable views is unchanged at 19: the
application had 19 all along, and the twentieth was never one of them.

### F-18 follow-up — LOW — RESOLVED — The Plant Configuration screen has a real source

The roadmap item left open above has been taken up, under the approval
*"endpoint and screen"*.

**The endpoint** is `backend/app/api/v1/topology.py`, mounted at
`/api/v1/topology`. It is **read-only**: the OpenAPI schema publishes `get`
on that path and nothing else, and a test asserts it. It reads the plant
from the application-scoped runtime — the same source the Plant Overview
reads — so a load-balanced request always sees the plant that owns the
engine. It requires `Permission.READ_CONFIG`, so an unauthenticated read is
refused with a 401.

The response publishes the plant's identity, its ratings, the configuration
file it was built from, and the inventory of its equipment. Two honesty rules
govern it:

- a value the topology does not declare is published as **absent**, not as a
  placeholder. The equipment models fall back on a placeholder manufacturer
  (`"Generic BESS"`) and on a placeholder plugin identifier, and a
  placeholder on a configuration screen reads as a configured vendor. The
  transformer of the reference plant therefore reports
  `manufacturer: null`, because the topology names no vendor for it.
- every illustrative parameter is labelled as illustrative, per
  `AGENTS.md` §2.14.

A platform with no plant attached answers with `plant_configured: false` and
a message. It does not answer with the inventory of some other plant, and it
does not answer with an error, because "no plant is configured" is a true
statement about the platform rather than a failure.

**The screen** is `frontend/src/views/PlantConfigurationView.tsx`, reachable
from the sidebar as *Plant Configuration*. It renders what the endpoint
reports and nothing else:

- a plant that is attached is shown with its identity, its ratings and its
  inventory, each item summarized by the rating its type carries;
- a rating the topology does not declare reads `NOT SPECIFIED`, never `0` —
  a "0.00 MW" rating reads as a measurement of a plant that cannot
  discharge, which is a different statement;
- a vendor the topology does not declare reads `NOT SPECIFIED`, never a
  placeholder;
- a platform with no plant says *No plant is attached* and shows no
  substitute;
- a platform that does not answer says *The platform did not answer* and
  shows no plant at all — the screen that this one replaces is exactly what
  it refuses to be.

The reachable view count is now 20. `tests/test_topology_api.py` (12 tests)
covers the endpoint; the view is covered by 15 component tests and 5 service
tests. The frontend suite grew from 176 to 199 tests.

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
| Local web HMI | **PARTIAL** | 20-view React + TypeScript SCADA, live telemetry, "SIMULATED DATA ONLY" labelling. **Ten of the 20 views read the backend; the other ten show the reference plant's illustrative properties and are labelled as such.** See F-16 |
| Historian | **IMPLEMENTED** | The ring buffer with zero-silent-loss disk overflow, the database flush and the read-only query API are implemented and tested. **The running platform now writes to the store: an application-layer recorder samples the running plant, subscribes to the command log, and flushes on the event loop, with the engine holding no database dependency.** See F-15 |
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
missing ORM-versus-migration comparison, and an unprotected `main` branch.

The verification pass did, however, surface four delivery defects that were
invisible from the source alone — an inert pytest configuration, an inert
coverage configuration, an unpinned CI toolchain that also polluted the
runtime image, and a release-critical SBOM generator with no unit test that
did not type-check. All four are fixed. They are recorded in §8.1 because the
fact that they were possible is itself a finding: a configuration file that
looks authoritative while changing nothing is a trap for the next engineer.

The first run on the CI provider then surfaced two further delivery defects
that no amount of local review could have found — a compose validation step
that could not satisfy the mandatory secret the compose file demands, and a
container image whose runtime layer carried a compiler toolchain. Both are
recorded in §8.5 and F-07, and both are fixed. The next run, on the corrected
files, was green across every job.

A later pass over the HMI found one functional gap that the earlier passes had
not looked for, and it is recorded here because it changes the mission
coverage table in §10. **The historian was never written to by the running
platform** (F-15). The subsystem was implemented, unit-tested and exposed
through read-only, permission-guarded endpoints — but nothing in
`backend/app/` constructed the `HistorianService` or called its recorder, so
in a running deployment the store held no rows and the three query endpoints
answered against a store that was never fed. This was a **HIGH** finding. It
was not a safety defect: the failure was a missing write path, not a
weakened guard, and nothing that reads the store could influence the
simulation. It is now **RESOLVED**: an application-layer recorder samples the
running plant, subscribes to the platform's single command write path, and
flushes to the database on the event loop, while the simulation engine keeps
no database dependency at all.

The same pass removed the reasons the gap was hard to see. Three screens
presented values the platform never produced (F-16); they now read the
backend and distinguish "the store holds rows", "the store holds none" and
"the query failed". The historian endpoints failed as an untranslated 500 and
had no API-level tests at all (F-17); they now fail as an explicit 503 and
are covered by eight tests. An unreachable view fabricated the active
configuration file (F-18); it was removed, and the Plant Configuration
screen that replaced it now reads a real, read-only topology endpoint.

### 11.2 Recommended actions, in order

1. ~~**Close the migration-metadata gap** (F-03). Add `target_metadata` and an
   ephemeral PostgreSQL service to the release job, then restore
   `alembic check`.~~ **Done.** The Alembic environment declares the ORM
   metadata, the release job builds the schema and compares it against the
   ORM against an ephemeral TimescaleDB service container, and the ORM now
   declares exactly the index set the migrations create.
2. ~~**Build the frontend test suite** (F-01) and the Playwright end-to-end
   path** (F-05), then raise the enforced floor.~~ **Done.** The component
   suite measures 176 tests and 98.02 % line coverage with an enforced 75 %
   floor, the Playwright project drives the built HMI against a hermetic mock
   platform, and both run as enforced pipeline gates.
3. **Apply the branch protection** (F-04). An administrator action, using the
   documented check names. The rule set is now executable and verifiable:
   `python scripts/apply_branch_protection.py --dry-run` prints exactly what
   would be sent, and `GITHUB_TOKEN=<token> python
   scripts/apply_branch_protection.py` applies it and then reads it back,
   exiting non-zero if what is in force is looser than what was documented.
4. ~~**Wire the historian into the running simulation** (F-15).~~ **Done.**
   The decision was taken under the approval *"recorder in the app layer"*,
   and the proposal was built as proposed: the simulation engine keeps its
   independence from the database (`AGENTS.md` §3, asserted by an AST scan of
   the `backend/app/simulation` package), and the recorder lives in the
   application layer, subscribing to what the engine publishes and persisting
   it with the simulation timestamp on every row. The write path never blocks
   a tick, and a failed commit rolls back to the disk overflow file rather
   than losing a row. The historian's mission coverage is **IMPLEMENTED**.
5. **Schedule the roadmap items** (F-06) explicitly, and keep them marked
   `NOT_IMPLEMENTED` until they exist. The warranty **read** path and its
   screen now exist, but no recorder writes the metrics, so the digital-twin
   calibration and warranty analysis of `AGENTS.md` §1 remains unimplemented.
6. ~~**Decide on the Plant Configuration screen** (F-18 follow-up).~~ **Done.**
   The decision was taken under the approval *"endpoint and screen"*. The
   read-only topology endpoint `/api/v1/topology` publishes the plant the
   platform is actually running, with the illustrative parameters labelled
   and the undeclared ones reported as absent; the Plant Configuration screen
   reads it and shows no substitute plant when the platform is silent or has
   none attached. The reachable view count is now 20.
7. **Close the low-severity items** (F-08, F-09, F-10, F-11) as part of the
   next maintenance pass. ~~F-10 is closed: the illustrative parameters carry
   a schema marker that defaults to labelling, the plant factory carries it
   into the runtime equipment, and a test asserts that every shipped example
   configuration states it.~~ ~~F-08 is closed: the runtime is the single
   write path to the plant and the engine, and the module-level helpers that
   offered a second route to the same state are removed.~~ ~~F-11 is closed:
   the whole repository is linted with one declared style — the same line
   length, the same rule selection and `E501` active in every tree — and a
   test fails if the two Ruff declarations ever diverge again.~~ ~~F-09 is
   closed: the platform has one dedicated, append-only, hash-chained
   operator-action journal that every command, setpoint change, configuration
   change, fault and operator action flows through, and the migration
   environment no longer silences the application's loggers.~~ ~~F-13 is
   closed: the system info endpoint reads the engine status from the
   application-scoped runtime, the same source the Plant Overview reads, and
   the divergent second implementation of that status is removed.~~ ~~F-14 is
   closed: the speed factor has one documented range that every boundary
   that accepts one enforces, and the screen reads the factor in force and
   sets it through the `SET_SPEED` control.~~

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
