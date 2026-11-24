# PowerTwin — CI/CD System Architecture and Operations Guide

## 1. Overview & CI/CD Architecture

The PowerTwin platform utilizes GitHub Actions for continuous integration, automated physics validation, security scanning, nightly regression testing, and versioned release packaging.

```text
+------------------------------------------------------------------------------------+
|                             POWERTWIN CI/CD PIPELINE                               |
+------------------------------------------------------------------------------------+
       |                        |                         |                       |
       v                        v                         v                       v
+--------------+       +------------------+       +---------------+       +---------------+
|   MAIN CI    |       | SECURITY SCAN    |       |    NIGHTLY    |       |    RELEASE    |
| (Parallel)   |       | (CodeQL, Trivy,  |       | (High-Stress, |       | (SBOM, Build, |
| - Backend    |       |  Audit, Secrets) |       |  Endurance)   |       |  Tarball)     |
| - Frontend   |       +------------------+       +---------------+       +---------------+
| - Physics    |
| - Docker     |
+--------------+
```

Every job in every workflow declares a `timeout-minutes` budget, so a hung
test can never consume a runner indefinitely.

---

## 2. Workflows & Triggers

| Workflow | File | Triggers | Purpose |
| :--- | :--- | :--- | :--- |
| **Main CI** | `.github/workflows/ci.yml` | `pull_request` (any branch), `push (main)`, `workflow_dispatch` | Fast-feedback testing, formatting, linting, type-checking, system validation |
| **Security** | `.github/workflows/security.yml` | `pull_request` (any branch), `push (main)`, `schedule (03:00 UTC)`, `workflow_dispatch` | CodeQL static analysis, pip/npm dependency audit, secret scanning, Trivy container scan |
| **Nightly** | `.github/workflows/nightly.yml` | `schedule (01:00 UTC)`, `workflow_dispatch` | Long-duration regression, multi-cycle degradation, large plant topologies, historian throughput, endurance campaign |
| **Release** | `.github/workflows/release.yml` | `push (tags: v*)`, `workflow_dispatch` | Version validation, migration validation, SBOM generation, container build, release tarball packaging |
| **Reusable Backend** | `.github/workflows/reusable-backend.yml` | `workflow_call` | Modular backend lint, type-check, test, coverage-gate and interpreter-compatibility jobs |
| **Reusable Frontend** | `.github/workflows/reusable-frontend.yml` | `workflow_call` | Modular frontend test, coverage-gate and build job |

> A pull request is tested whatever branch it targets. Restricting the trigger
> to `main` would leave the feature branch of a pull request unverified until
> the moment it is merged.

### 2.1 Python interpreter matrix

The canonical interpreter is **Python 3.12**; it produces the coverage report
and enforces the coverage policy. The **Backend Tests (Python 3.13)** and
**Backend Tests (Python 3.14)** jobs run the same suite on the newer
interpreters with `fail-fast: false`, so that an interpreter-specific
regression is caught by the pipeline rather than by a user.

This matrix exists because of a concrete defect: the Modbus TCP gateway
teardown relied on CPython 3.14 `asyncio` behaviour that differs from 3.12.
The regression test that guards it now runs on every interpreter.

All three interpreters of the matrix were exercised locally against this
revision, and the whole gate set — formatting, linting, strict type checking,
315 tests, the coverage policy, the migration validation, the release-version
validation and the endurance campaign — passed on each. The endurance
fingerprint was the identical `58d28d0aab4cd788` on all three, so the
determinism is a property of the model rather than of a single CPython build.

### 2.2 Static analysis configuration

Ruff and mypy are both configured **inside the repository**, so that the local
result and the CI result are the same:

| Tool | Configuration | Scope |
| :--- | :--- | :--- |
| Ruff (format and lint) | `backend/pyproject.toml` | `backend/` — line length 100 |
| Ruff (format and lint) | `ruff.toml` (repository root) | `scripts/`, `tests/`, `plugins/` — line length 88 |
| Mypy | `backend/pyproject.toml` (`strict = true`) | `backend/`, `plugins/`, `scripts/` |

Ruff resolves its configuration **per file**, by walking up the directory tree
from the file being checked. `scripts/`, `tests/` and `plugins/` had no
configuration file of their own, so their effective rule set was inherited from
whatever configuration happened to exist outside the repository, or from Ruff's
defaults when nothing was found.

The practical consequence was that **the lint result depended on the machine**:
a developer and the CI runner could legitimately disagree about whether the
same commit passed, and a green local run did not prove that CI would be
green. The root `ruff.toml` pins the rule set inside the repository and closes
that gap.

The two rule selections are the same (`E`, `F`, `I`, `B`, `UP`, with `B008`
ignored), so the whole repository is linted with one documented style. The line
lengths differ because the files of `scripts/`, `tests/` and `plugins/` are
already formatted at 88 characters; keeping that value preserves the existing
formatting instead of reformatting code that the change has nothing to do
with.

There is exactly one documented exception: **`E501` is ignored for the 88-wide
trees and stays active in `backend/`.** Ruff's formatter never reflows a
docstring or a comment, so a tree that is correctly formatted at 88 characters
can still contain long prose lines that no formatter run will ever shorten.
Enabling `E501` there would demand prose-only edits that the formatter itself
declines to make, and would reject well-formatted files. In `backend/` the line
length is 100 and the formatter's output already satisfies `E501`, so the check
is meaningful and is kept there.

---

## 3. Branch Protection & GitHub Settings

> **These settings are applied by a repository administrator in the GitHub
> settings. They are documented here, and deliberately NOT applied by this
> repository, because the branch-protection configuration of a repository is
> not part of its source code.**

To maintain repository integrity, configure the following settings in GitHub
Repository Settings → Branches → Branch protection rules → `main`:

- **Require a pull request before merging** (with at least one approval).
- **Require status checks to pass before merging**, selecting exactly these
  check names, which are the names of the jobs that the workflows produce:

  | Check name | Workflow | Job |
  | :--- | :--- | :--- |
  | `Backend Lint & Typecheck` | `reusable-backend.yml` | `backend-lint-and-typecheck` |
  | `Backend Unit & Integration Tests` | `reusable-backend.yml` | `backend-test` |
  | `Backend Tests (Python 3.13)` | `reusable-backend.yml` | `backend-interpreter-compatibility` |
  | `Backend Tests (Python 3.14)` | `reusable-backend.yml` | `backend-interpreter-compatibility` |
  | `Frontend Lint, Test & Build` | `reusable-frontend.yml` | `frontend-ci` |
  | `System Engineering & Physics Validation` | `ci.yml` | `system-engineering-ci` |
  | `Infrastructure & Docker Build Validation` | `ci.yml` | `infrastructure-ci` |
  | `Final CI Summary` | `ci.yml` | `ci-summary` |

- **Require linear commit history**.
- **Require signed commits**.
- **Do not allow bypassing the above settings**, so that the checks cannot be
  skipped by an administrator.
- **Block force pushes and deletions**.

---

## 4. Coverage Policy

The coverage policy is **enforced**, not merely documented. It is defined once,
in `scripts/check_coverage.py`, and it is applied to the
`pytest-cov` JSON report by the `Backend Unit & Integration Tests` job:

```bash
python scripts/check_coverage.py coverage.json
```

The script exits with a non-zero status when a floor is not met, which fails
the job and therefore blocks the merge.

### 4.1 Enforced backend floors

The floors sit a small margin below the coverage that was measured when they
were set. The measured column is the value produced by the **canonical
interpreter, Python 3.12**, which is the interpreter that generates the
coverage report in the pipeline. It shows how much headroom each floor still
has.

| Domain | Enforced floor (lines) | Measured | Enforced floor (branches) | Measured | Roadmap target |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Global** | **80 %** | 82.44 % | **60 %** | 63.34 % | — |
| Simulation engine (`backend/app/simulation/`) | 75 % | 77.58 % | 53 % | 55.03 % | 90 % |
| Battery and BMS (`backend/app/models/battery/`) | 88 % | 90.10 % | 72 % | 74.44 % | 90 % |
| PCS, BoP and grid models | 87 % | 89.02 % | 67 % | 69.41 % | 90 % |
| Equipment controller | 89 % | 91.06 % | 81 % | 83.33 % | 90 % |
| PPC and EMS | 89 % | 92.11 % | 74 % | 76.83 % | 85 % |
| Protocol gateway (`backend/app/communication/`) | 75 % | 77.99 % | 63 % | 65.38 % | 85 % |
| API and historian | 76 % | 79.43 % | 49 % | 51.72 % | 80 % |
| Plant topology | 90 % | 93.49 % | 82 % | 84.21 % | 85 % |
| Equipment plugins (`plugins/`) | 76 % | 78.55 % | 55 % | 57.78 % | 85 % |

The figure moves by a few tenths of a point between interpreters, because the
number of executable statements differs slightly between CPython versions. On
Python 3.14 the same suite measures 82.18 % globally instead of 82.44 %, and
Python 3.13 measures 82.44 %. Every interpreter satisfies every floor, and the
headroom above each floor is larger than that variation.

Two properties make this gate trustworthy:

- a policy scope that no longer matches any source file is reported as a
  **violation**, so a renamed or moved directory can never silently stop
  being enforced;
- the floors are always at or below the measured coverage, so the gate is
  satisfiable. A gate that cannot be met is not a gate.

The roadmap targets in the last column are the long-term goal for the
safety-critical domains. They are **not** enforced today, because the
measured coverage does not reach them. Closing the gap is tracked as
remaining work, not presented as done.

### 4.2 Enforced frontend floors

The frontend policy lives in `frontend/vite.config.ts` and is enforced by the
`npm run test:coverage` step of the `Frontend Lint, Test & Build` job.

| Scope | Lines | Functions | Statements | Branches |
| :--- | :--- | :--- | :--- | :--- |
| Global (`src/**`) | 4 % | 5 % | 4 % | not enforced |
| `src/services/api.ts` | 18 % | 38 % | 18 % | not enforced |
| `src/services/auth.ts` | 11 % | — | 11 % | not enforced |

The frontend test suite currently contains **4 tests in 2 files**. Every one
of the 19 SCADA view components and the React hooks are untested, so the
real coverage of the HMI is **4.15 % lines, 5.95 % functions and 0 %
branches**.

The coverage configuration counts every file of `src/`, including the files
that no test touches. Without that, the untested views would disappear from
the report and the figure would look far better than the reality.

> **The 75 % frontend target that an earlier revision of this guide
> published was aspirational and was never implemented.** The Vitest
> configuration declared a 75 % threshold against a measured 4.15 %, and the
> coverage provider was not even installed, so the check could not run. Both
> the configuration and this guide now state the enforced floor and the
> measured value. Reaching 75 % requires component tests for the SCADA views
> and is tracked as remaining work.

---

## 5. Release Engineering

### 5.1 Release version validation

A release version is used for the tag of a published release, the name of the
release tarball, the tag of the container images and the version recorded in
the software bill of materials. A malformed value would therefore propagate
into every artefact, so the value is validated **before anything is built**:

```bash
python scripts/validate_release_version.py "${RELEASE_VERSION}"
```

The accepted format is a semantic version with a mandatory `v` prefix:

```text
vMAJOR.MINOR.PATCH
vMAJOR.MINOR.PATCH-PRERELEASE
vMAJOR.MINOR.PATCH-PRERELEASE+BUILD
```

The version is resolved from the pushed tag on a tag build, and from the
`release_version` workflow input on a manual dispatch. A manual dispatch is a
**packaging rehearsal**: it produces and uploads the artefacts, but it does
not publish a GitHub release, because a published release must correspond to
a real tag. The version is validated in both cases.

### 5.2 Database migration validation

The release workflow validates the Alembic migration graph **offline**, with
no database and no credentials:

```bash
python scripts/validate_migrations.py
```

It verifies that the graph has exactly one head and that the whole chain
renders to SQL. Every migration is therefore importable, every
`down_revision` resolves and every operation is well formed, and the check is
deterministic and reproducible.

> **NOT IMPLEMENTED:** comparing the ORM metadata against the migrations.
> That check is what `alembic check` does, and it requires a live database
> connection *and* a non-empty `target_metadata` in `migrations/env.py`.
> Neither was available in CI, so the command failed with an import error
> before the release could be built at all. It is listed in section 8.

### 5.3 Software bill of materials

The SBOM is an SPDX-2.3 document generated by `scripts/generate_sbom.py` from
the dependency inventories that are recorded during the build:

- `release_artifacts/python_packages.json` — `pip list --format=json`,
- `release_artifacts/npm_packages.json` — `npm ls --json --all`, which
  includes the complete transitive tree and not only the direct dependencies.

The SBOM and both inventories are **part of the release archive**, and their
SHA-256 checksums are written to `SHA256SUMS`.

The document is valid SPDX 2.3: every package carries a unique `SPDXID`, a
concluded and a declared license and a copyright statement. The document
namespace is derived from the release version and the creation timestamp, so
two releases never share a namespace. The creation timestamp is the real time
at which the SBOM was generated and can be pinned through `SOURCE_DATE_EPOCH`
for a byte-for-byte reproducible release.

License verification against the distribution rules remains a **manual**
process and is documented by the SBOM itself.

The generator is covered by **13 tests** in `tests/test_ci_scripts.py`, which
assert the SPDX field set, the uniqueness of the identifiers and of the
document namespace, the reproducibility under a pinned `SOURCE_DATE_EPOCH`, the
flattening of the transitive Node.js dependency tree and its depth limit, and
the rejection of a missing, empty, malformed or wrongly shaped inventory. A
malformed inventory is **reported as a failure**, never reduced to an empty
SBOM, because an empty document is indistinguishable from a project with no
dependencies at all.

### 5.4 Release contents

The release archive contains the configuration, the deployment definitions, the
documentation, the built Web HMI, the compose file, the engineering rules and
the release evidence (SBOM, dependency inventories and checksums).

---

## 6. Nightly Endurance Campaign

The nightly pipeline runs `scripts/endurance_campaign.py`, which answers three
questions that a unit test cannot:

- does the engine still produce **bit-identical** results after a long run,
  that is, does the determinism survive a large number of ticks,
- does the engine **drift** over time, for example through a state variable
  that is never reset,
- what is the **throughput** of the engine, so that a performance regression
  is visible in the nightly report.

The campaign builds the reference plant from its YAML topology, seeds every
random process, runs 360 000 ticks (one simulated hour at 100 Hz) twice with
the same seed and compares a fingerprint of the resulting engine snapshot.
The snapshot identifier and the wall-clock creation time are excluded from
the fingerprint because they are non-deterministic by design.

The seed is taken from the `random_seed` input of the workflow, so a specific
seed can be replayed on demand. The report is written to
`release_artifacts/endurance_campaign.json` and uploaded with the other
nightly artefacts.

> A nightly run is never cancelled by a newer run: the campaign is long
> running, and cancelling it would waste the runner time it already used.

---

## 7. Security Scanning

| Check | Tool | Scope | Failure mode |
| :--- | :--- | :--- | :--- |
| Static analysis | CodeQL | Python, JavaScript | Report in the Security tab |
| Python dependency audit | `pip-audit` 2.10.1 | `backend/requirements.txt` | Job fails on a known vulnerability |
| npm dependency audit | `npm audit --audit-level=high` | `frontend/package-lock.json` | Job fails on a high or critical advisory |
| Secret scanning | TruffleHog (`--only-verified`) | Full history | Job fails on a verified secret |
| Container scan | Trivy (`CRITICAL,HIGH`) | Backend image | Job fails on a critical or high finding |

The auditing tools are pinned in `backend/requirements-ci.txt`, separately from
the runtime requirements, so that a change of the auditing tool can never
silently change the behaviour of a release build.

---

## 8. Known Limitations of the CI/CD System

- **The metadata comparison of the migrations is NOT IMPLEMENTED.** The
  offline validation of section 5.2 checks the graph and the rendering, not
  the agreement between the ORM models and the migrations.
- **The frontend coverage is 4.15 %.** The enforced floor is a regression
  guard, not a quality claim. The SCADA view components have no component
  tests.
- **The branch protection of `main` is documented, not applied.** The setting
  is a property of the repository configuration on GitHub, not of the source
  code, and must be applied by an administrator.
- **The dependency ranges of `backend/requirements.txt` are not pinned.** The
  Python dependencies are declared with `>=`, so two builds of the same commit
  can resolve to different versions. The lock file of the frontend is pinned
  and `npm ci` is used. Pinning the Python dependencies is remaining work.
- **`pip-audit` audits the declared ranges, not a lock file.** It resolves
  the ranges at audit time, so the result describes the ranges and not one
  exact build.
- **The endurance campaign covers the reference plant only.** It does not
  exercise every topology variant.
- **The release workflow publishes only on a tag.** A manual dispatch is a
  packaging rehearsal and never creates a GitHub release.

---

## 9. Local Execution Commands

Developers can execute all CI checks locally prior to opening a pull request.

### Environment

The pipeline installs the runtime requirements first and the CI toolchain
second, so the pinned tool versions win whatever the runtime ranges resolve
to. A local environment should be built the same way:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-ci.txt
```

Run every command **from the repository root**. Ruff, pytest and coverage all
discover their configuration by walking up from the working directory, so a
command started elsewhere reads a different configuration — which is exactly
the defect that section 2.2 describes.

### Backend Tests & Quality Checks

```bash
# Formatting check
PYTHONPATH=. ruff format --check backend plugins tests scripts

# Linting check
PYTHONPATH=. ruff check backend plugins tests scripts

# Static type checking
PYTHONPATH=. mypy --config-file backend/pyproject.toml backend plugins scripts

# Unit & integration tests with coverage
PYTHONPATH=. pytest --cov=backend/app --cov=plugins --cov-branch \
  --cov-report=json:coverage.json

# Enforce the coverage policy locally
PYTHONPATH=. python scripts/check_coverage.py coverage.json

# Property-based physics tests (Hypothesis)
PYTHONPATH=. pytest tests/test_hypothesis_physics.py

# CI helper scripts
PYTHONPATH=. pytest tests/test_ci_scripts.py
```

### Frontend Tests & Build

```bash
cd frontend

# TypeScript type check
npm run lint

# Component unit tests (Vitest)
npm test

# Coverage with the enforced policy
npm run test:coverage

# Production build
npm run build

# Dependency audit
npm audit --audit-level=high
```

### Release Helpers

```bash
# Validate a release version
python scripts/validate_release_version.py v1.0.0

# Validate the migration graph offline
python scripts/validate_migrations.py

# Run the endurance campaign
PYTHONPATH=. python scripts/endurance_campaign.py --ticks 36000 --seed 42 --repeats 2
```

---

## 10. Security and Hardware Isolation Policy

> [!CAUTION]
> **SAFETY & HARDWARE ISOLATION INVARIANT**:
>
> 1. The CI/CD system operates strictly in **SIMULATION ONLY** mode.
> 2. All automated protocol tests (Modbus TCP) bind strictly to loopback (`127.0.0.1:5020`).
> 3. Workflows **NEVER** scan external IP subnets or attempt to connect to physical battery or inverter hardware.
> 4. Automated deployment to live BESS plants or OT networks is strictly prohibited.
> 5. The release workflow contains no credential, no connection detail of real equipment and no outbound call to a device.
