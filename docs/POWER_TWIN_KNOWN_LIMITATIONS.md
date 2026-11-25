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
`9928aec` completed with **every job green**:

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
