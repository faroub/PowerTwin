# PowerTwin — CI/CD System Architecture and Operations Guide

## 1. Overview & CI/CD Architecture

The PowerTwin platform utilizes GitHub Actions for continuous integration, automated physics validation, security scanning, nightly regression testing, and versioned release packaging.

```
+-----------------------------------------------------------------------------------+
|                            GITHUB ACTIONS PIPELINE                                |
+-----------------------------------------------------------------------------------+
       |                        |                         |                      |
       v                        v                         v                      v
+--------------+       +------------------+       +---------------+      +---------------+
|   MAIN CI    |       | SECURITY SCAN    |       |   NIGHTLY     |      |    RELEASE    |
| (Parallel)   |       | (CodeQL, Trivy,  |       | (High-Stress, |      | (SBOM, Build, |
| - Backend    |       |  Audit, Secrets) |       |  Regression)  |      |  Tarball)     |
| - Frontend   |       +------------------+       +---------------+      +---------------+
| - Physics    |
| - Docker     |
+--------------+
```

---

## 2. Workflows & Triggers

| Workflow | File | Triggers | Purpose |
| :--- | :--- | :--- | :--- |
| **Main CI** | `.github/workflows/ci.yml` | `pull_request`, `push (main)`, `workflow_dispatch` | Fast-feedback testing, formatting, linting, type-checking, system validation |
| **Security** | `.github/workflows/security.yml` | `pull_request`, `push (main)`, `schedule (03:00 UTC)`, `workflow_dispatch` | CodeQL static analysis, pip/npm dependency audit, secret scanning, Trivy container scan |
| **Nightly** | `.github/workflows/nightly.yml` | `schedule (01:00 UTC)`, `workflow_dispatch` | Long-duration regression, multi-cycle degradation, large plant topologies, historian throughput |
| **Release** | `.github/workflows/release.yml` | `push (tags: v*)`, `workflow_dispatch` | Tagged production builds, SBOM generation, container scanning, release tarball packaging |
| **Reusable Backend** | `.github/workflows/reusable-backend.yml` | `workflow_call` | Modular backend test and coverage job |
| **Reusable Frontend** | `.github/workflows/reusable-frontend.yml` | `workflow_call` | Modular frontend test and build job |

---

## 3. Branch Protection & GitHub Settings

To maintain repository integrity, configure the following settings in GitHub Repository Settings:
- **Require Branch Protection for `main`**:
  - Require status checks to pass before merging: `Backend Lint & Typecheck`, `Backend Unit & Integration Tests`, `Frontend Lint, Test & Build`, `System Engineering & Physics Validation`, `Infrastructure & Docker Build Validation`, `Final CI Summary`.
  - Require linear commit history.
  - Require signed commits.
  - Block force pushes and deletions.

---

## 4. Coverage Threshold Policy

PowerTwin enforces minimum code coverage targets by domain module:

| Domain Module | Line/Branch Coverage Target |
| :--- | :--- |
| **Simulation Engine** (`backend/app/simulation/`) | **90%** |
| **Battery and BMS** (`backend/app/models/battery/`) | **90%** |
| **PCS & Electrical Models** (`backend/app/models/pcs/`, `bop/`, `grid/`) | **90%** |
| **Equipment Controller** (`backend/app/controllers/equipment_controller.py`) | **90%** |
| **PPC and EMS** (`backend/app/controllers/ppc.py`, `ems.py`) | **85%** |
| **Plugin Manager** (`plugins/`) | **85%** |
| **API & Historian** (`backend/app/api/`, `historian/`) | **80%** |
| **Frontend Web HMI** (`frontend/src/`) | **75%** |

---

## 5. Local Execution Commands

Developers can execute all CI checks locally prior to opening a pull request:

### Backend Tests & Quality Checks
```bash
# Formatting check
PYTHONPATH=. ruff format --check backend plugins tests

# Linting check
PYTHONPATH=. ruff check backend plugins tests

# Static type checking
PYTHONPATH=. mypy backend plugins

# Unit & Integration tests with coverage
PYTHONPATH=. pytest --cov=backend/app --cov=plugins --cov-branch

# Property-based physics tests (Hypothesis)
PYTHONPATH=. pytest tests/test_hypothesis_physics.py
```

### Frontend Tests & Build
```bash
cd frontend

# TypeScript type check
npm run lint

# Component unit tests (Vitest)
npm test

# Production build
npm run build
```

---

## 6. How to Produce a Release

To trigger an automated release build:
1. Ensure all PRs are merged to `main` and main CI is green.
2. Create and push a semver tag:
   ```bash
   git tag -a v1.0.0 -m "Release v1.0.0 — PowerTwin Industrial BESS Simulator"
   git push origin v1.0.0
   ```
3. GitHub Actions will execute `.github/workflows/release.yml`, generating SBOM metadata, scanning containers, running full test suites, and publishing the release tarball to GitHub Releases.

---

## 7. Security and Hardware Isolation Policy

> [!CAUTION]
> **SAFETY & HARDWARE ISOLATION INVARIANT**:
> 1. The CI/CD system operates strictly in **SIMULATION ONLY** mode.
> 2. All automated protocol tests (Modbus TCP) bind strictly to loopback (`127.0.0.1:5020`).
> 3. Workflows **NEVER** scan external IP subnets or attempt to connect to physical battery or inverter hardware.
> 4. Automated deployment to live BESS plants or OT networks is strictly prohibited.
