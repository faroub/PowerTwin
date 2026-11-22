# PowerTwin — Baseline Report (Pre-Remediation State)

Generated: 2026-11-22 | Branch: `remediation/baseline` (off main 95769ae)

## 1. Environment

- Python 3.12 (CI pinned), toolchain ruff 0.17.6 / mypy 2.4.1 / pytest 9.2.0
- Node 24.14.1 / npm 11.19.0 / Vite 5.2.2 / Vitest 1.6.1
- PyPy 3.14.4 in default `python3` (used for local verification)

## 2. Verification Pipeline Results (reproducible locally)

| Step | Command | Result |
|---|---|---|
| Python format | `ruff format --check backend plugins tests` | 141 files already formatted |
| Python lint | `ruff check backend plugins tests` | **PASSED** (after baseline fixes) |
| Python typecheck | `mypy --config-file backend/pyproject.toml backend plugins` | Success, 119 source files |
| Backend tests | `pytest -q` | 120 passed |
| Backend coverage | `--cov=backend/app --cov=plugins --cov-branch` | 80% |
| Frontend lint | `npm run lint` (`tsc --noEmit`) | PASS |
| Frontend tests | `npm test` (`vitest run`) | 2 files, 4 tests PASS |
| Frontend build | `npm run build` | Built 3 assets (181 kB) |
| Docker compose | `docker compose config --quiet` | OK |
| Docker backend | `docker build -f deployment/Dockerfile.backend .` | OK |
| Docker frontend | `docker build -f deployment/Dockerfile.frontend .` | OK |

## 3. CI Defects Found

### 3.1 Ruff lint failure (fixed)

The `backend-ci / Backend Lint & Typecheck` job failed with exit code 1 because ruff reported 21 errors:

- 3 × I001 import sorting (`factory.py`, `validator.py`, `env.py`)
- 18 × E501 line too long — docstrings and comments exceeding 100 chars

**Action taken:** fixed I001 (ruff --fix) and re-wrapped all 18 E501 lines (docstrings/comments only — no functional change).

### 3.2 GitHub Action SHA failures (fixed)

Six of eight pinned action references in `.github/workflows/` did not resolve to a known commit/tag: every workflow job failed at *action setup*. All eight are now API-verified.

| `actions/setup-node@v4.0.2` | `60ed15d5...` | `60edb5dd545a775178f52524783378180af0d1f8` |
| `actions/upload-artifact@v4.0.0` | `50541007...` | `c7d193f32edcb7bfad88892161225aeda64e9392` |
| `github/codeql-action@v3.24.0` | `e889a00d...` | `e8893c57a1f3a2b659b6b55564fdfdbbd2982911` |
| `aquasecurity/trivy-action@v0.20.0` | `d43c1f16...` | `b2933f565dbc598b29947660e66259e3c7bc8561` |
| `trufflesecurity/trufflehog@v3.63.1` | `37e20e8b...` (invalid repo name) | `d69de658b262d67abe200d6eff9100934bc8f7a4` |
| `softprops/action-gh-release@v2.0.4` | `9d7c94cfd0a17b...` | `9d7c94cfd0a1f3ed45544c887983e9fa900f0564` |

`actions/checkout@b4ffde65...` and `actions/setup-python@0a5c6159...` were valid and unchanged. The old path `trufflesecurity/trufflehog-action` points to a repository that does not exist; the action is published at `trufflesecurity/trufflehog` (root `action.yml`).
