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

### 2.3 Dependency resolution and hash verification

The runtime dependencies are declared in `backend/requirements.txt` as version
**ranges**, because a range is what a human maintains: it says which major
version the project is written against and leaves the exact build to the
resolver. The **resolution** is `backend/requirements.lock`, which was
generated with `pip-compile --generate-hashes` and commits, for all 35
packages including the transitive ones, one exact version and the SHA-256
hash of every distribution of that version.

| Artefact | Holds | Who maintains it |
| :--- | :--- | :--- |
| `backend/requirements.txt` | The declared ranges, and the extras that are wanted | A human, together with the source change that needs them |
| `backend/requirements.lock` | The exact resolution, with the hashes | `pip-compile`, regenerated and committed alongside a change to the file above |
| `backend/requirements-ci.txt` | The build tooling, pinned to exact versions | A human, on a deliberate tooling upgrade |

**Everything that installs the runtime dependencies installs the lock, with
`--require-hashes`.** That applies to the container image, to the main CI
workflow, to the reusable backend workflow on all three interpreters, to the
nightly campaign and to the release workflow. Pip refuses to install an
artefact whose hash does not match the recorded one, so a build either
reproduces the recorded dependency set exactly or fails. It also refuses a
lock that is missing a package or that carries an unhashed entry, which makes
the lock's own completeness a property that the pipeline proves on every run.

**The lock cannot drift away from the declarations.**
`scripts/check_dependency_lock.py` compares the two and reports a declared
requirement that is missing from the lock, a locked version that no longer
satisfies its declared range, a locked entry without a hash, a locked entry
that no declared requirement reaches, and a dependency edge that names a
package the lock does not contain. The pipeline runs it as a step, and the
test suite exercises it, so a range that is changed without regenerating the
lock fails the build rather than passing silently.

**The runtime image contains only the packages of the lock.** Python 3.12 no
longer installs `setuptools` into a fresh virtual environment, and nothing in
the service needs it. The build tool that is used to install the dependencies
is removed again afterwards, together with the dependency it drags in — the
wheel builder requires `packaging`, and removing the builder alone leaves
that dependency behind. The base image's own `pip` is removed as well, so the
shipped image carries no package installer at all.

That last statement is a claim, and claims of this kind are worth proving
rather than leaving to the reading of an uninstall chain.
`scripts/verify_locked_environment.py` compares the distributions that are
actually installed against the packages the lock pins, and reports a locked
package that is missing, one that is installed at a different version, and one
that is installed but that the lock does not pin.

| Mode | Used by | What it requires |
| :--- | :--- | :--- |
| strict | the container build | the installed set is **exactly** the locked set |
| default | the pipeline | every locked package is present at exactly the pinned version; additional packages are reported and permitted |

The container build runs the strict mode, so an image that carries a package
no hash covers **fails to build** rather than being published. The pipeline
runs the default mode, which asserts that the CI toolchain install did not
quietly replace a runtime package with another version — a check that is
worth having precisely because it is the kind of substitution that a range
based install would perform silently.

The script uses the standard library only. That is deliberate: it has to run
inside the container image, whose virtual environment carries nothing but the
packages of the lock.

`pip-audit` audits the **lock**, not the declared ranges. Auditing the ranges
reports the newest version each range would resolve to, which is not
necessarily the version that is installed or that is shipped.

To change a runtime dependency, edit `backend/requirements.txt`, regenerate
the lock and commit both files:

```bash
pip-compile --generate-hashes --strip-extras \
    --output-file=backend/requirements.lock backend/requirements.txt
python scripts/check_dependency_lock.py
```

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
| Global (`src/**`) | **75 %** | **75 %** | **75 %** | **75 %** |
| `src/services/api.ts` | 95 % | 95 % | 95 % | 80 % |
| `src/services/auth.ts` | 95 % | 95 % | 95 % | 95 % |
| `src/components/*.tsx` | 95 % | 95 % | 95 % | 90 % |
| `src/views/*.tsx` | 90 % | 90 % | 90 % | 70 % |

The frontend test suite contains **151 tests in 11 files**, and the measured
coverage of the HMI is **98.28 % lines, 98.82 % functions, 98.29 %
statements and 85.92 % branches**. Every one of the 19 SCADA view
components, the shared components, the React hooks and the entry point are
covered.

The coverage configuration counts every file of `src/`, including the files
that no test touches. Without that, the untested views would disappear from
the report and the figure would look far better than the reality.

> **The 75 % frontend target that an earlier revision of this guide
> published was aspirational and was never implemented.** The Vitest
> configuration declared a 75 % threshold against a measured 4.15 %, and the
> coverage provider was not even installed, so the check could not run. The
> component suite now measures 98.28 % lines, and **75 % is the enforced
> floor** for every metric, with tighter floors on the modules that carry the
> session, the telemetry polling, the shared components and the views. The
> binding of the directory-scoped floors was verified by deliberately raising
> them until the gate failed, so they are known to bind and not merely
> declared.

### 4.3 End-to-end testing of the HMI

The HMI is exercised end to end by **Playwright**, in a real browser, against
the built artefact. The suite is configured in `frontend/playwright.config.ts`
and the specs live in `frontend/e2e/`.

| Property | Value |
| :--- | :--- |
| Base URL | `http://127.0.0.1:4173` (loopback only) |
| Server under test | `vite preview` serving `frontend/dist/` |
| Browser | Chromium, installed by `npx playwright install --with-deps chromium` |
| Command | `npm run test:e2e` (a fresh `npm run build` runs first) |
| Pipeline step | `Run Playwright End-to-End Tests` of the `Frontend Lint, Test & Build` job |

The suite is **hermetic by construction**. There is no backend behind the
preview server: `frontend/e2e/mockPlatform.ts` answers every `/api/v1/**`
request inside the browser, **aborts** any path it does not model, and
**blocks** any request to a host other than the local preview server. The
specs assert that neither an unmodelled path nor a blocked host occurred, so
a spec cannot quietly depend on an endpoint nobody modelled or on a network
that should not exist.

The specs cover the operator path — log in, read the overview, pause the
engine behind its confirmation, observe the result, log out — and the safety
posture: the session token travels in memory and in the `Authorization`
header only, never in `localStorage`, `sessionStorage` or a cookie; a backend
that is not ready is reported as disconnected rather than replaced by
invented figures; and a refused control action is reported as a failure
without the engine state being set to a successful one.

`frontend/tsconfig.json` includes `e2e/` and `playwright.config.ts`, so the
end-to-end code is type-checked by the same `npm run lint` gate as the
application. `tests/test_deployment_images.py` asserts the properties of
this configuration from the Python suite, so the end-to-end gate cannot be
silently removed from the pipeline.

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
| Container scan — operating system | Trivy (`CRITICAL,HIGH`, fixable only) | Backend and frontend images | Job fails on a critical or high finding **that has a published fix** |
| Container scan — application packages | Trivy (`CRITICAL,HIGH`, strict) | Backend and frontend images | Job fails on **any** critical or high finding, fixed or not |

The auditing tools are pinned in `backend/requirements-ci.txt`, separately from
the runtime requirements, so that a change of the auditing tool can never
silently change the behaviour of a release build.

### 7.1 Why the container scan is split into two policies

A single scan with one severity threshold cannot be satisfied by any image
that is based on a current distribution release, and the reason is structural
rather than a matter of configuration.

The backend image is built on the official `python:3.12-slim` image, pinned by
digest, which is Debian trixie. Debian currently has **no published fix** for
13 advisories that affect packages the base image necessarily contains —
`util-linux`, `login`, `bsdutils`, `ncurses`, `sqlite3`, `openssl`, the
`systemd` libraries, `perl-base` and `libacl1`. Trivy reports each of them as
HIGH. A scan that fails on every HIGH finding therefore fails for reasons that
no change to this repository can address, and a gate that can never be met is
a gate that everyone learns to ignore.

The two policies separate the two package families by the party that owns
them:

- **Operating-system packages belong to the distribution.** The scan fails on
  every critical or high advisory **that has a fix available**, and the image
  build runs `apt-get upgrade` so that the newest published patches are always
  present. The day Debian publishes a fix, the advisory stops being unfixed,
  the scan starts reporting it, and the build fails until the image picks the
  patch up. The gate therefore cannot silently rot, and it cannot be satisfied
  by ignoring an advisory: no ignore file is used at all.
- **Application packages belong to this project.** Every one of them can be
  changed by editing a pin in `backend/requirements.txt`, so the scan holds
  them to the strictest policy: no critical and no high advisory is accepted,
  whether or not a fix exists. Because this scan is restricted to the
  application package family, the inherited Debian advisories cannot mask a
  finding in it.

The measured result against the rebuilt images is **0 critical, 0 high with a
fix**, for both images. The full, unfiltered scan of the backend image reports
53 high findings across 21 packages, all 13 advisory identifiers of which are
inherited from the unmodified base image and all of which are unfixable
upstream. The frontend image reports zero findings of every severity. The
residual risk and the reasoning behind it are recorded in
`docs/POWER_TWIN_KNOWN_LIMITATIONS.md` §4.11.

### 7.2 The compose validation in the pipeline

`docker-compose.yml` declares `POSTGRES_PASSWORD` as mandatory, using the
`${POSTGRES_PASSWORD:?...}` form, so the compose file cannot even be parsed
without it. The pipeline validates the syntax and the interpolation of the
compose file, and supplies a **validation-only placeholder** for the duration
of that one step. The placeholder is not a credential, it grants access to
nothing, it is never written to a file, it is never pushed anywhere and it
never starts a container. The mandatory-variable requirement in
`docker-compose.yml` is deliberately left untouched, so a real deployment
still has to supply its own secret.

---

## 8. Known Limitations of the CI/CD System

- **The metadata comparison of the migrations is NOT IMPLEMENTED.** The
  offline validation of section 5.2 checks the graph and the rendering, not
  the agreement between the ORM models and the migrations.
- **The frontend coverage floors are a regression guard, not a quality
  claim.** The suite measures 98.28 % lines, so the 75 % global floor has a
  wide margin, and the directory-scoped floors are the ones that actually
  bite: a view or a shared component that loses its tests fails the gate
  even when the global figure barely moves. The branch coverage of 85.92 % is
  the weakest metric, and the 75 % branch floor is the binding global
  constraint.
- **The end-to-end suite runs against a mock platform, not against the real
  backend.** That is deliberate — the suite must never be able to address a
  running installation — but it means the specs prove the HMI's own
  behaviour, not the agreement between the HMI and the FastAPI backend. That
  agreement is covered by the backend's own HTTP tests.
- **The branch protection of `main` is documented, not applied.** The setting
  is a property of the repository configuration on GitHub, not of the source
  code, and must be applied by an administrator.
- **The lock file is a snapshot.** `backend/requirements.lock` pins the
  runtime dependencies to the versions that were current when it was
  generated. A newly published upstream release enters it only when somebody
  regenerates it, which is the intended behaviour but means that the lock
  ages until it is regenerated. It was resolved on Python 3.12 and is
  installed with `--require-hashes` on 3.12, 3.13 and 3.14.
- **The CI toolchain is pinned without hashes.** `backend/requirements-ci.txt`
  pins the linters, the type checker and the test runner to exact versions.
  They are build tooling and never enter a deployed artefact, so they are not
  hash-verified the way the runtime dependencies are.
- **The endurance campaign covers the reference plant only.** It does not
  exercise every topology variant.
- **The release workflow publishes only on a tag.** A manual dispatch is a
  packaging rehearsal and never creates a GitHub release.

---

## 9. Local Execution Commands

Developers can execute all CI checks locally prior to opening a pull request.

### Environment

The pipeline installs the runtime lock first and the CI toolchain second, so
the pinned tool versions win whatever the runtime ranges resolve to. A local
environment should be built the same way:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r backend/requirements.lock
pip install -r backend/requirements-ci.txt
```

Installing the lock rather than the declared ranges is what makes a local run
and a pipeline run exercise the same package versions.

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

# End-to-end path (Playwright, against the built artefact on the loopback
# interface, with a hermetic mock platform). The first run needs the browser:
#   npx playwright install --with-deps chromium
npm run test:e2e

# Dependency audit
npm audit --audit-level=high
```

### Release Helpers

```bash
# Validate a release version
python scripts/validate_release_version.py v1.0.0

# Validate the migration graph offline
python scripts/validate_migrations.py

# Check that the dependency lock still matches the declared requirements
python scripts/check_dependency_lock.py

# Check that the installed environment is the one the lock describes
python scripts/verify_locked_environment.py --lock backend/requirements.lock

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
