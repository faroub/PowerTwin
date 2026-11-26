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

- **The running platform never writes to the store.** The historian
  subsystem is implemented and unit-tested: `backend/app/historian/service.py`
  provides a `HistorianService` with a ring buffer, a zero-silent-loss disk
  overflow, a database flush and a replay path, and
  `backend/app/historian/query.py` reads the tables it writes. **Nothing in
  `backend/app/` constructs that service or calls `record_telemetry`,
  `record_command`, `record_alarm`, `flush_buffer_to_db` or
  `flush_all_to_db`** — the service is instantiated only in the test suite.
  In a running deployment the tables `telemetry_data`, `command_records` and
  `alarms_and_events` therefore stay empty, and the read-only query
  endpoints answer with zero rows against a store that was never fed. This
  is recorded as **F-15** in `docs/POWER_TWIN_FINAL_AUDIT_REPORT.md` and is
  **OPEN**: connecting the recorder is an architecture change that
  `AGENTS.md` §7.5 requires approval for. It must not be resolved by putting
  the database inside the simulation engine (`AGENTS.md` §3).
- **The warranty metrics are never written either.** The endpoint
  `GET /api/v1/historian/warranty/{container_id}` reads metrics that no
  recorder produces, so it answers 404 for every container in a running
  deployment. The screen reports that honestly: *"No warranty metrics are
  recorded for container 'X'."* The digital-twin calibration and warranty
  analysis of `AGENTS.md` §1 remains **NOT IMPLEMENTED** (see §3).
- **Ring Buffer Before TimescaleDB**: Telemetry is held in a bounded in-memory ring buffer and flushed to the database. The disk-overflow fallback writes append-only JSON files; it protects against silent loss but it is not a queryable time-series store.
- **The `alarms_and_events` query path has no supporting index.** The
  deployed schema carries indexes on `telemetry_data`
  (`idx_telemetry_query`, `idx_telemetry_run`), on `command_records`
  (`idx_cmd_target`) and on `users` (`idx_users_username`), but none on
  `alarms_and_events`, whose query filters on `equipment_id` and orders by
  `timestamp_ns`. The ORM used to declare three individual column indexes
  there that no migration ever created, so the models claimed an index the
  database did not have; reconciling the two removed the false claim. The
  performance characteristic is unchanged — it was always an unindexed scan —
  and adding the index is a schema change that needs its own migration and its
  own approval.

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

The frontend test suite contains **176 tests in 11 files**, and the measured
coverage is **98.02 % of lines, 99.21 % of functions, 98.03 % of statements
and 88.02 % of branches**. Every SCADA view, the shared components, the login
flow, the telemetry hook, the API client and the application entry point are
covered.

The enforced floors in `frontend/vite.config.ts` are **75 %** for every
metric globally, with tighter floors on the modules that carry the session
(`src/services/api.ts`, `src/services/auth.ts`), on the shared components
(`src/components/*.tsx`) and on the views (`src/views/*.tsx`). A directory
floor is evaluated against the **aggregate** of the files it matches, so a
view that loses its tests is caught by its own directory's floor even when
the global figure barely moves. The binding of those floors was verified by
raising them deliberately until the gate failed.

What the suite does **not** prove: the branch coverage of 88.02 % is the
weakest metric, and the 75 % branch floor is the binding global constraint.
The suite exercises the HMI against a mocked backend, so it proves the HMI's
own behaviour and not the agreement between the HMI and the real FastAPI
backend; that agreement is covered by the backend's own HTTP tests.

### 4.2 The End-to-End Suite Runs Against a Mock, Not Against the Backend

`AGENTS.md` §4 names Playwright for frontend end-to-end tests, and a
Playwright project now exists (`frontend/playwright.config.ts`, specs in
`frontend/e2e/`). The operator path — log in, read the overview, act on the
simulation engine behind its confirmation, observe the result, log out — is
exercised automatically in a real browser against the built artefact, and so
is the full engine lifecycle: the operator starts the engine, stops it, and
each action travels with the session token. The **wall-clock speed factor**
is exercised the same way: the screen shows the factor in force, the
operator asks for a new one, the confirmation names the requested factor,
and the `SET_SPEED` request travels with the session token.

The suite is **hermetic by construction**: there is no backend behind the
preview server. `frontend/e2e/mockPlatform.ts` answers every `/api/v1/**`
request inside the browser, aborts any path it does not model, and blocks any
request to a host other than the local preview server on `127.0.0.1`. That is
what makes the suite safe to run anywhere, and it is also its limitation: the
specs prove the HMI's behaviour, **not** the behaviour of the platform as a
whole against a live backend. The browser coverage is Chromium only; no
WebKit, Firefox or mobile viewport is exercised.

### 4.3 The Python Runtime Dependencies Are Now Pinned, and What That Does Not Cover

`backend/requirements.txt` declares every runtime dependency with `>=`, as
the file a human maintains. The **resolution** of those declarations is
`backend/requirements.lock`: every dependency, including the transitive ones,
pinned to one exact version and carrying the SHA-256 hash of every
distribution of that version.

The container image and every workflow install the lock with
`--require-hashes`, so a build either reproduces the recorded artefact
exactly or fails. The lock is checked against the declarations by
`scripts/check_dependency_lock.py`, which the pipeline runs and which the test
suite exercises, so the lock cannot silently drift away from the ranges it
was generated from. The size of the gap this closed was observed during the
final audit: the same source tree resolved to FastAPI 0.165 and bcrypt 5.0 on
a clean Python 3.12 environment, against 0.118 and 4.x on the machine it had
been developed on.

The **installed set** is checked as well, in the direction the hash check
cannot reach. `scripts/verify_locked_environment.py` compares the
distributions that are actually installed against the packages the lock pins.
The container build runs it in strict mode, so an image carrying a package
that no hash covers fails to build; the pipeline runs it in the default mode,
so a runtime package that was quietly substituted during the CI toolchain
install fails the job. This matters because the build tool used to install
the dependencies has a dependency of its own, which removing the tool alone
leaves behind.

**What the pinning does not cover.** A lock records the resolution that was
produced on the day it was generated. It does not make the *declared ranges*
reproducible, and it does not prove that the pinned versions are free of
vulnerabilities. Four things remain outside it:

- **The lock is a snapshot, not a live resolution.** A newly published
  release of a dependency does not enter the lock until somebody regenerates
  it. That is the intended behaviour — a change to the deployed artefact has
  to be a visible, reviewable change to a committed file — but it means that
  the lock ages until it is regenerated.
- **The lock was resolved for one interpreter.** It was generated on Python
  3.12 and is installed with `--require-hashes` on 3.12, 3.13 and 3.14. The
  three interpreters were each verified to install it and to pass the suite,
  but a package that publishes no wheel for a future interpreter would have
  to be built from its source distribution, which the hash check still
  enforces but which is slower and needs a compiler.
- **The CI toolchain is pinned separately.** `backend/requirements-ci.txt`
  pins the linters, the type checker and the test runner to exact versions,
  as it did before, and those pins are not hash-verified. They are build
  tooling: they never enter a deployed artefact.
- **A hash proves integrity, not provenance.** The lock records the SHA-256
  hash of every distribution, and `--require-hashes` makes pip refuse any
  artefact whose hash does not match. That proves the installed artefact is
  the one the lock recorded. It does not, on its own, prove where that
  artefact was published.

The frontend **is** pinned, by `frontend/package-lock.json` and `npm ci`.

### 4.4 The Drift Gate Does Not Compare Primary Keys, and It Runs Only at Release Time

The release pipeline **does** compare the ORM metadata against the migration
history: `backend/migrations/env.py` sets `target_metadata = Base.metadata`,
and the release job runs `alembic upgrade head` followed by `alembic check`
against an ephemeral TimescaleDB service container. A model column added
without a migration now fails the release. See `docs/CI_CD_GUIDE.md` §5.2.1.

Two limits of that gate remain, and they are properties of Alembic's
autogenerate rather than of the implementation:

- **Primary keys are not compared.** Alembic compares tables, columns,
  indexes, constraints and types, but it does not compare primary keys, so a
  model whose primary key was changed without a migration is not detected by
  the gate. Such a change needs a migration and a reviewer's attention.
- **The gate runs at release time, not on every pull request.** A drift
  introduced on a branch is caught when the release is built, not when the
  branch is merged. Moving the gate into the pull-request pipeline would catch
  it earlier, at the cost of a database container on every pull request.

**The gate has been executed, and its negative case has been verified.** The
release job's TimescaleDB service container and the two Alembic commands had
never run on a GitHub runner, because publishing a release requires pushing a
`v*` tag. The same commands were therefore rehearsed locally against the
**same digest-pinned image** the workflow uses
(`timescale/timescaledb@sha256:5d7a2f9d…`), with the same environment
variables and the same throwaway credentials:

```text
alembic upgrade head  ->  001_initial_schema, then 002_user_accounts
alembic check         ->  "No new upgrade operations detected."   (exit 0)
```

The offline graph validator of the same job, `scripts/validate_migrations.py`,
reports a single head (`002_user_accounts`), renders 101 SQL statements and
exits zero.

The gate was then probed with an **undeclared table** added to the migrated
schema. `alembic check` detected it —
`Detected removed table 'rehearsal_drift_probe'` — and **failed with exit
code 255**, so a model changed without a migration does reach a failed
release rather than a silent pass.

What remains unverified is the **rest** of the release job: the artifact
upload, the SBOM generation, the checksum manifest and the image builds in
that workflow have not been executed on a GitHub runner either. The
TimescaleDB container and the two Alembic commands are now the only part of
that job that has been run, and they have been run against the image and the
commands the workflow itself uses.

### 4.5 Branch Protection Is Documented, Not Applied

The required status checks for `main` are listed in `docs/CI_CD_GUIDE.md` §3.
The branch-protection configuration itself is a property of the repository on
GitHub, not of the source code, and **must be applied by a repository
administrator**.

### 4.6 The Workflow Definitions Have Now Run on GitHub, and Two Defects Were Found

The six workflow files **have now been executed by GitHub Actions**. The
first run on the merged `main` branch was the first one that exercised the
whole pipeline against a commit that carries all of the remediation work.
Every backend, frontend, system-engineering, secret-scanning, dependency-audit
and CodeQL job passed. Two jobs failed, and both failures were real defects
rather than flakes:

1. **The compose validation failed.** `docker-compose.yml` declares
   `POSTGRES_PASSWORD` as mandatory, using the `${POSTGRES_PASSWORD:?...}`
   form, but the pipeline step that renders the compose file did not supply
   one. The step aborted with exit code 15 and the message *required variable
   POSTGRES_PASSWORD is missing a value*. The requirement itself was correct
   and was not weakened; the step was corrected to supply a validation-only
   placeholder.
2. **The container scan failed.** The backend image was built as a single
   stage that retained the compiler toolchain, and the scan reported 158
   high-severity operating-system findings. See §4.11.

Both defects were reproduced locally before anything was changed, and both
were fixed and re-verified locally: the compose file now renders with the
placeholder and still refuses to render without one, and the rebuilt image
passes both scan policies with zero fixable findings and starts, reports
healthy and upholds the safety invariants.

**The gap has since been closed.** The corrected workflow files were merged
into `main` and executed by GitHub Actions themselves. The run on commit
`9928aec` completed with **every job green**, and the run on the dependency-
locking change, commit `4d69c20`, did the same — all twelve jobs, including
the two new gates that check the installed environment against the lock:

| Workflow | Job | Result |
| :--- | :--- | :--- |
| Main CI Workflow | Infrastructure & Docker Build Validation | `success` |
| Main CI Workflow | Backend Unit & Integration Tests | `success` |
| Main CI Workflow | Backend Lint & Typecheck | `success` |
| Main CI Workflow | Backend Tests (Python 3.13) | `success` |
| Main CI Workflow | Backend Tests (Python 3.14) | `success` |
| Main CI Workflow | System Engineering & Physics Validation | `success` |
| Main CI Workflow | Frontend Lint, Test & Build | `success` |
| Main CI Workflow | Final CI Summary | `success` |
| Security & Vulnerability Scanning | Docker Image Security Scan (Trivy) | `success` |
| Security & Vulnerability Scanning | Python & npm Dependency Security Audit | `success` |
| Security & Vulnerability Scanning | Secret & Credential Scanning | `success` |
| Security & Vulnerability Scanning | CodeQL Static Security Analysis | `success` |

**What this does and does not prove.** It proves that the workflow
definitions are syntactically valid, that the corrected expressions evaluate
as intended on the runner, that the compose file renders, that the image
builds and passes both scan policies, and that the container starts,
reports healthy and upholds the safety invariants. It does **not** turn the
pipeline into a proof of correctness: a green run means that no gate
failed, not that the gates cover every possible defect. The gaps that remain
are listed in §4.1, §4.2, §4.3 and §4.4, and they are unaffected by this run.

The rest of the local evidence still stands. The backend gates were run on the
canonical interpreter **Python 3.12**, in a clean virtual environment built
from the two requirements files exactly as the pipeline builds it, and again
on **Python 3.13** and **Python 3.14**: formatting, linting, strict type
checking, the test suite with coverage, the coverage policy, the migration
validation, the release-version validation and the endurance campaign all
passed on all three. The frontend gates were run as well and all passed.
`pip-audit` was executed against the declared ranges and against the fully
resolved build, and reported no known vulnerabilities in either;
`npm audit --audit-level=high` reported 0 vulnerabilities.

The determinism fingerprint was identical on all three interpreters
(`58d28d0aab4cd788`), so the determinism is a property of the model rather
than of one CPython build.

### 4.7 The Endurance Campaign Covers the Reference Plant Only

The nightly determinism campaign builds the 10 MW / 20 MWh reference plant.
It does not exercise every topology variant, every vendor plugin combination,
or the 50 MW / 200 MWh variant under long-duration load.

### 4.8 The Simulation Runtime Has a Single Write Path

The application-scoped runtime is the only way to attach or detach a plant
and its engine. The module-level `set_active_simulation_engine(...)` helpers
that used to offer a second route to the same state are gone: a plant is
attached with `SimulationRuntime.attach_plant` and detached with
`SimulationRuntime.drop`, and `tests/test_simulation_runtime.py` asserts that
neither module can offer the old way back.

### 4.9 The Operator-Action Journal Is Fail-Open When a Write Fails

The platform has one dedicated, append-only, tamper-evident operator-action
journal (`backend/app/core/operator_journal.py`). Every command, setpoint
change, configuration change, fault and operator action flows through it, and
`OperatorActionJournal.verify()` reports the first break in its hash chain.

The boundary worth knowing about is what happens when a write **fails**. The
failure is not swallowed: it is raised as an `OperatorJournalError`, logged as
an error, and the journal marks itself `degraded` and exposes the message.
But the action that was being recorded is **not** rolled back, and the entry
is **not** written later. The trail therefore has a gap.

This is deliberate. A simulation action cannot be undone — the engine has
already advanced by the time the record is written — and failing closed would
make the whole plant uncontrollable the moment the disk fills. The operator
can tell "nothing happened" from "the record could not be written" by reading
the journal's `degraded` flag and `last_error`; the trail itself does not
record the gap, and the journal is not a substitute for a signed external
record. A deployment that needs the trail to survive the loss of the disk
should copy it off the host.

### 4.10 The Illustrative Label Does Not Yet Reach the Operator's Screen

`AGENTS.md` §2.14 requires illustrative parameters to be clearly labelled. The
label is now carried by the data rather than by prose alone: every topology
configuration model has an `illustrative: bool` field that defaults to `True`,
the plant-level marker is derived from the items and refuses an under-labelled
plant, the plant factory carries the marker into the runtime
`EquipmentMetadata.is_illustrative` of every equipment it builds, and both
shipped example configurations state it explicitly.
`tests/test_illustrative_parameters.py` asserts all of that.

What is still missing is the last step: the HMI has no topology-configuration
API, so the operator does not see the marker on screen. The label reaches the
configuration file, the runtime equipment metadata, the historian and the
build log, but a viewer of the HMI is told the data is *simulated* without
being told that the *parameters* are illustrative.

### 4.11 The Base Image Carries Upstream Advisories That Debian Has Not Fixed

The backend image is built on the official `python:3.12-slim` image, pinned by
digest, which is Debian trixie. Debian has **not yet published a fix** for
13 advisories that affect packages the base image necessarily contains. Trivy
reports each of them as HIGH severity:

| Advisory | Affected package | Subject |
| :--- | :--- | :--- |
| CVE-2025-69720 | `ncurses-base`, `ncurses-bin`, `libncursesw6`, `libtinfo6` | Buffer overflow in the terminal handling library |
| CVE-2026-9538 | `perl-base` | Denial of service in the archive reader |
| CVE-2026-107494 | `openssl`, `libssl3t64`, `openssl-provider-legacy` | Denial of service via an unbounded QUIC frame |
| CVE-2026-124709 | `openssl`, `libssl3t64`, `openssl-provider-legacy` | Memory leak in the QUIC handling |
| CVE-2026-16742 | `libsystemd0`, `libudev1` | Local privilege escalation in `systemd-homed` |
| CVE-2026-54369 | `libacl1` | Symlink traversal privilege escalation |
| CVE-2026-76642 | `util-linux`, `mount`, `login`, `bsdutils` and their libraries | Failed external mount helper retains privileges |
| CVE-2026-78408 | `util-linux`, `mount`, `login`, `bsdutils` and their libraries | `nsenter` leaks the root cgroup |
| CVE-2026-78409 | `util-linux`, `mount`, `login`, `bsdutils` and their libraries | Detached-tree resolution in `X-mount.subdir` |
| CVE-2026-78410 | `util-linux`, `mount`, `login`, `bsdutils` and their libraries | Restricted bind mounts do not pin the source tree |
| CVE-2026-119373 | `libsqlite3-0` | Denial of service via a heap-based buffer overflow |
| CVE-2026-119374 | `libsqlite3-0` | Code execution via a corrupted FTS5 index |
| CVE-2026-119379 | `libsqlite3-0` | Code execution via a crafted session extension |

**These are inherited, not introduced.** A scan of the *unmodified* base image
reports the identical set of advisory identifiers, so no package that this
project chose to install contributes to them. The practical consequence is
that **no change to this repository can remove them**: only the distribution
can, by publishing a fixed package.

**What has been done about it.** The backend image was rebuilt as a
multi-stage image so that the runtime layer carries no compiler toolchain at
all. The single-stage image previously retained `build-essential` and
`libpq-dev`, which dragged in `linux-libc-dev`, the Kerberos chain, the
ncurses and Perl trees and the whole GCC and binutils toolchain. That change
removed **105** of the 158 high-severity findings and shrank the image from
609 MB to 281 MB. The runtime layer additionally runs `apt-get upgrade`, so
the newest patches the distribution has published are always applied.

**How the residual risk is judged.** The affected code paths are not
reachable from the service. The container runs as a fixed non-root user
(uid 10001) with no added capabilities, no host namespaces, no privileged
mounts and no `systemd` instance; the mount helpers, `nsenter`, `login` and
`systemd-homed` are not invoked by the application, by the health probe or by
the compose file. The service opens no QUIC connection, and the SQLite
advisories concern the FTS5 and session extensions, which this application
does not use — the platform stores its history in PostgreSQL/TimescaleDB. The
risk of exploitation through the platform itself is therefore assessed as
negligible, but the residual risk is **not zero** and it is **not under this
project's control**.

**How the gate deals with it.** The container scan is split into two policies,
as described in `docs/CI_CD_GUIDE.md` §7.1. The operating-system scan fails
on every critical or high advisory **that has a published fix**, so the
residual set cannot be ignored into permanence: the moment Debian publishes a
fix, the advisory stops being unfixed, the scan starts reporting it and the
build fails until the image picks the patch up. The application-package scan
applies the strictest policy and is unaffected by the inherited set. No
ignore file is used anywhere.

**What this limitation is.** It is an accurate statement that the deployed
backend image is not free of known-high upstream advisories. The image is
**not** claimed to be free of them, and the platform is **not** claimed to be
suitable for a production deployment that treats the container as a hardened
artefact. The frontend image, which is based on `nginx:alpine`, reports **zero**
findings at every severity.

### 4.12 The Runner Repairs a Set of Lifecycle Races, and the Control Endpoint Is Still Synchronous

The runner now holds three lifecycle properties that it did not hold before:
a stop is final (no tick starts behind the back of a stop), a start always
leaves a loop that really ticks (a superseded thread cannot clear the state
of the generation that replaced it), and a step advances the clock by exactly
the number of ticks it was asked for. The contract is stated in
`docs/04_SIMULATION_ENGINE_SPECIFICATION.md` §3.1 and asserted by
`tests/test_simulation_runner.py` and `tests/test_simulation_runtime.py`.

What the repair does **not** change:

- **A stop waits for the tick in flight.** The tick and the check of the run
  flag are one atomic unit, so a stop cannot overtake a tick that has
  already begun. The cost is that the stop of a runner whose tick blocks is
  delayed by that tick: the `timeout_s` of `stop_with_timeout` bounds the
  **join**, not the acquisition of the action lock, so a task that never
  returns delays the stop indefinitely. A task that blocks forever is a bug
  in the task, and the platform does not yet police task runtimes.
- **The control endpoint executes a step synchronously.** `POST
  /simulation/control` runs the tick batch on the event loop thread, so a
  batch of 1000 ticks occupies the loop for roughly 3 s on the reference
  plant. That is why `MAX_STEP_TICKS` is 1000 (10 s of simulated time at the
  100 Hz tick rate); a longer fast-forward belongs to the headless runner.
  The batch is deliberately *not* moved to a worker thread: running it
  concurrently would let a `START` interleave with it and break the
  guarantee that a step advances the clock by exactly the requested number
  of ticks.
- **The tick count is bounded, not unlimited.** A tick count of zero, a
  negative count or a count above `MAX_STEP_TICKS` is refused with HTTP 400
  and recorded in the operator-action journal as `REJECTED` /
  `INVALID_STEP_COUNT`. It is not corrected to a different command.

### 4.13 The HMI Reaches Every Engine Lifecycle Action and the Speed Factor

The simulation view offers **Start**, **Pause**, **Stop**, **Single Step** and
**Reset**, each behind the same confirmation modal, so the whole engine
lifecycle is reachable from the operator's screen. The start and the stop
were missing: the engine comes up in the `STOPPED` state, and without them
the operator could only pause a run that something else had begun.

The **wall-clock speed factor** is reachable from the screen as well. The
card that reports it now shows the factor the engine actually has in force
rather than a fixed `1.0 x`, and a **Wall-Clock Pacing** card sets it
through the `SET_SPEED` control the API implements. The screen refuses a
factor outside the permitted range without sending it, and names the
requested factor in the confirmation modal, so the operator is told what is
about to happen before it happens.

Two limitations remain and are **not** removed by this:

- **The factor is set in multiples of the tick rate, not in wall-clock
  units.** A factor of `4.0` means the simulation clock advances four times
  faster than real time; it does not mean "four ticks per second", and it
  does not change the resolution of the clock. The tick rate stays at
  100 Hz regardless of the factor.
- **A factor of `0.0` means "run as fast as the host allows", not "stop".**
  It is a valid request and a distinct one from the paused state; the card
  labels it `MAX (unpaced)` so that it cannot be mistaken for a stopped
  engine. On a desktop host an unpaced run consumes the whole core it runs
  on, which is a property of the host and not a promise the platform makes
  about throughput.

### 4.14 The Engine Status Is Read From the Application That Owns the Plant

`GET /api/v1/info` is where the HMI takes the engine state it shows the
operator. It used to resolve that state through the module-level fall-back
runtime — the instance that exists for callers without an application
handle — and never through the runtime that actually owns the plant. The
consequence was that the endpoint answered `NOT_CONNECTED` while the Plant
Overview reported the running plant: two reads of the same plant disagreed,
and the Simulation Control screen displayed a plant that was running as one
that was not connected.

The endpoint now resolves the **application-scoped** runtime from the request,
exactly as the Plant Overview does, and reports `runtime.status()`. The
second, divergent implementation of the engine status — the one that computed
`is_running` from the engine state rather than from the runner — has been
removed, so the two endpoints can no longer drift apart.
`tests/test_startup.py::test_system_info_reports_the_engine_that_owns_the_plant`
asserts that both endpoints describe the same engine, and it fails against
the unrepaired code with `assert 'NOT_CONNECTED' == 'RUNNING'`.

Two things about the endpoint are worth knowing and are **not** changed:

- It is **read-only and unauthenticated**. It exposes the project metadata,
  the safety report and the engine state; it exposes no control surface and
  no credential. The telemetry and control endpoints remain behind the
  bearer-token guard.
- The engine status carries the **wall-clock speed factor in force**, so
  that the screen can show the factor that is actually pacing the clock
  rather than the one it was built with. The factor is a pacing parameter
  of the simulation clock; it does not change the safety posture the
  endpoint reports, and it is not a control surface.

The runtime docstrings claimed that start-up binds the module fall-back to
the application. It does not, and never did — an application owns the runtime
that holds its plant, and two applications never share one. The docstrings
now describe the actual binding, and the test that asserted the false claim
with a tautology (`runtime is default_runtime or runtime is not
default_runtime`) now asserts the truth.

### 4.15 Nine of the Nineteen HMI Views Read the Backend

The HMI carries **19** SCADA views. Nine of them read the platform:

| View | Reads |
| :--- | :--- |
| Plant Overview | `GET /api/v1/overview` |
| Alarms | `GET /api/v1/overview` |
| PCS | `GET /api/v1/overview` |
| Battery Systems | `GET /api/v1/overview` |
| Grid / POI | `GET /api/v1/overview` |
| Simulation Control | `GET /api/v1/info`, `POST /api/v1/simulation/control` |
| System Settings | `GET /api/v1/info` |
| Historian | `GET /api/v1/historian/telemetry`, `…/commands`, `…/alarms` |
| Warranty Metrics | `GET /api/v1/historian/warranty/{container_id}` |

The **other ten** — the equipment detail views for the BMS, the transformer,
the switchgear, the auxiliary package, the equipment controller, the PPC, the
EMS, the equipment library, the plugin manager, the scenario manager and the
single-line diagram — render the reference plant's **illustrative**
equipment parameters. They carry the `SimulatedDataNotice` that
`AGENTS.md` §2.14 requires, so the operator is told the numbers are
illustrative, but they are not live readings.

(The login screen, `frontend/src/components/LoginView.tsx`, is a shared
component rather than a view and reads `POST /api/v1/auth/login`.)

The reason is that the backend exposes **no per-equipment telemetry
endpoint**. `/api/v1/overview` answers at plant level only; there is no
route that returns the measurements of one piece of equipment. Building one
is an interface change and is approval-gated under `AGENTS.md` §7.5, so it
has not been built.

The removed `ConfigurationView` is part of the same story. It was unreachable
from the navigation and displayed a fabricated `configs/dev.yaml` as *the
active configuration*. It has been deleted rather than fixed, because a real
Plant Configuration screen needs a read-only topology endpoint that does not
exist yet.

### 4.16 The HMI Reads the Historian, and the Historian Is Empty

The Historian screen runs real queries against the real endpoints and
reports exactly what they answer: rows, no rows, or a failure. What it
cannot show is **history**, because nothing feeds the store — see §2.6. The
screen therefore reads correctly and answers nothing, which is an honest
statement about the platform rather than a defect in the screen.

The distinction matters for anyone reading a screenshot of the screen: *"The
store holds no rows"* is what a correctly-wired screen shows against an
unfed store, and it is indistinguishable on screen from *"the store holds no
rows because the run has not been recorded"*. Only the audit report's F-15
distinguishes them today.

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
