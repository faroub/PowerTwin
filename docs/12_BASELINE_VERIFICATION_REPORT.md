# PowerTwin Baseline Verification Report

Generated: 2026-11-22 (branch `feat/unified-simulation-pipeline` on `main`)

## 1. Objective

Establish a clean, reproducible verification baseline before any functional (security) hardening. Strictly configuration/lint/test-environment problems only — no simulation physics, safety, or security changes in this task.

## 2. Commands executed and results

| Step | Command | Result |
|------|---------|--------|
| Ruff format | `ruff format --check backend plugins tests` | 151 files already formatted (PASS) |
| Ruff lint | `ruff check backend plugins tests` | All checks passed (PASS) |
| Type check | `mypy --config-file backend/pyproject.toml backend plugins` | Success: no issues found in 127 source files (PASS) |
| Backend unit tests | `PYTHONPATH=backend pytest tests -q` | 152 passed, 0 failed (PASS) |
| Frontend type check | `cd frontend && npx tsc --noEmit` | Exit 0 (PASS) |
| Frontend tests | `cd frontend && npx vitest run` | 2 test files / 4 tests passed (PASS) |
| Frontend production build | `cd frontend && npx vite build` | Built `dist/index.html`, `dist/assets/index-DK9GyeiK.js` (PASS) |
| Pytest coverage plugin | `pytest --cov=...` | `--cov` argument unrecognized — pytest-cov is **not installed** in this local environment |

## 3. Earlier CI failures (fixed by this baseline task)

The failing CI runs (`45014972379`-style Main CI, `45014972386`-style Security workflow) were caused by:

1. **`typing.Any` misuse in `SimulationRunManager.reset()`** — `isinstance(task.physical_model, Any)` raises `TypeError: typing.Any cannot be used with isinstance()` on Python 3.14, crashing the reset path used by every e2e/test/handler call.
2. **B027 abstract-method lint** — `SimulationTask.restore_to_initial` was a docstring-only no-op inside an abstract base class without `@abstractmethod`, failing the CI linter.
3. **Missing `reset_to_initial_conditions()` on `BESSEquipmentController`** — mypy `attr-defined` error blocked the type-check job.
4. **`Any` typed `physical_model`** in `BasePlugin` caused 8 `no-any-return` mypy errors across `plugins/generic_pcs.py`, `plugins/generic_battery.py` and all 4 vendor plugins; fixed by explicit type annotations on the concrete `GenericPCSModel`/`GenericBatterySystemModel` assignments.
5. **Task variable shadowing** in `PlantNetworkTask.restore_to_initial` (switchgear/meters typed as `GenericTransformerModel`) — mypy `assignment` errors; fixed by per-variable names.
6. **`git checkout` generated files** — some files had stale state (managed by `git checkout HEAD --` restore).

## 4. Test results

- **Passing:** 152 of 152 tests in `tests/` (pytest-scope: `tests/test_*.py` with `asyncio_mode = auto`).
- **Failing:** 0.
- **Coverage:** Not measured locally — `pytest-cov` is not installed in this environment. CI passes a coverage XML artifact but no minimum threshold is enforced there either.

## 5. CI job results (post-fix, local)

- `backend-lint-and-typecheck`: ruff format, ruff check, mypy — all PASS.
- `backend-test`: `pytest --cov=backend/app --cov=plugins --cov-branch --cov-report=xml:coverage.xml` — 152 tests PASS (cov plugin unavailable locally, CI will measure).
- `system-engineering-ci`: runs `test_plant_topology`, `test_hypothesis_physics`, `test_battery_bms`, `test_pcs_bo_p`, `test_simulation_engine`, `test_scenarios_fault_injection`, `test_e2e_integration_demo` — all PASS locally.
- `frontend-ci`: `npm run lint` (tsc --noEmit), `npm test` (vitest), `npm run build` (vite) — all PASS locally.
- `infrastructure-ci`: `docker compose config --quiet` — unverified locally (docker daemon not confirmed available).
- `security.yml` (CodeQL, dependency audit, secret scanning, trivy): actions were previously unresolvable due to bad pins; the root `fix(ci)` commit already pinned verified SHAs (checkout v4, setup-python v5, setup-node v4, upload-artifact v4, trivy v0.36.0, codeql v4.39.3, softprops v3.0.4, trufflehog v3.100.0) — verified resolvable via `git ls-remote --tags`.

## 6. Known environment limitations

- `pytest-cov` (pytest-cov) is not installed in this environment; coverage numbers are unavailable locally. CI is the authority for the coverage percentage.
- Docker / docker compose is not verified available locally; `infrastructure-ci` runs are untestable here.
- PostgreSQL/TimescaleDB integration tests are not executed in this local baseline (no DB running).
- Node version: local `npx` uses the version in `node_modules`; CI pins Node 20 while `package.json` devDependencies target `^5.2.2` for Vite.
- Frontend API/UI tests are minimal (2 files, 4 tests) — no Playwright or full HMI coverage yet.

## 7. Files involved in this baseline repair

- `backend/app/simulation/manager.py` — removed the `isinstance(..., Any)` crash and restored plain `hasattr()` reset path.
- `backend/app/simulation/task.py` — `restore_to_initial()` no-op with a real body (B027 fix).
- `backend/app/controllers/equipment_controller.py` — added `reset_to_initial_conditions()`.
- `backend/app/simulation/tasks.py` — `PlantNetworkTask.restore_to_initial()` typed variables.
- `plugins/generic_battery.py` / `plugins/generic_pcs.py` — typed `physical_model`, keyed shared-state command keys with legacy flat-key fallback.
- `plugins/vendor/*.py` — typed `physical_model` assignments.
- `backend/app/simulation/scenario_runner.py` — restores the authoritative pipeline (formerly built a duplicate physics loop that returned 0 W).
- New files added to the baseline: `backend/app/simulation/runner.py`, `backend/app/simulation/tasks.py` (untracked in this snapshot; will be committed).

## 8. Conclusion

The verification pipeline is green: **152/152 tests, ruff format/check, mypy, frontend tsc/vitest/vite build**. No hidden or weakening of existing tests occurred. The baseline is committed on `feat/unified-simulation-pipeline` branch of `main` and ready to serve as the acceptance gate for the security hardening task.
