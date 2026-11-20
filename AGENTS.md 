# BESS Platform — AI Coding and Engineering Rules

## 1. Project mission

Build a modular Battery Energy Storage System (BESS) simulator and emulator for industrial and utility-scale applications.

The platform must support:
- Complete internal BESS simulation.
- Battery, BMS, PCS/inverter, transformer, switchgear, auxiliary and grid models.
- Equipment controller, PPC and EMS.
- POI and grid-frequency simulation.
- Grid services and energy-market scenarios.
- Vendor-specific equipment plugins.
- Local web HMI and historian.
- Controller-in-the-loop (CIL) and, in a later controlled phase, hardware-in-the-loop (HIL).
- Digital-twin calibration and warranty analysis.

## 2. Non-negotiable safety rules

1. The default application mode is SIMULATION ONLY.
2. No code may connect to, discover, scan, command or write to real industrial equipment unless a separately approved hardware-integration task explicitly authorizes it.
3. Never create a default route, protocol connection, credential, IP address or configuration that could target real equipment.
4. All external hardware interfaces must be disabled by default and require explicit configuration and deliberate operator enablement.
5. Clearly separate simulated devices, external controller connections and physical hardware connections.
6. Never bypass, disable or weaken BMS, PCS, protection, interlock, watchdog or emergency-stop logic.
7. Do not implement safety-critical protection as an unvalidated software substitute for certified hardware protection.
8. Reject invalid, stale, out-of-range, contradictory or incorrectly timestamped commands.
9. Apply safe command limits and validate commands at every relevant boundary.
10. Record all commands, setpoint changes, configuration changes, faults and operator actions in an auditable log.
11. Never silently fall back from a real-device connection to a simulated device, or vice versa.
12. Never expose writable control interfaces to an untrusted network.
13. Do not claim that a model is manufacturer-accurate unless its behavior has been validated against authoritative documentation or test data.
14. All illustrative equipment parameters must be clearly labelled as illustrative.

## 3. Architecture rules

- Keep the simulation engine independent of the HMI, database, EMS and manufacturer-specific implementations.
- Use standardized, typed interfaces for all equipment.
- Keep physical models, equipment behavior models, communication emulators and controllers separate.
- Put manufacturer-specific behavior in plugins, not in the generic core.
- Make plant topology and equipment quantities configuration-driven.
- Support mixed manufacturers and multiple equipment configurations.
- Use explicit SI units internally.
- Every measurement and command must have a timestamp, quality and source.
- Distinguish requested setpoints, accepted commands, actual outputs and measured values.
- Use a central simulation clock and deterministic simulation scheduling.
- Avoid global mutable state.
- Avoid circular dependencies.
- Keep modules independently testable.

## 4. Engineering rules

- Use Python 3.12+ with type hints.
- Use Pydantic for validated configuration and API models.
- Use NumPy/SciPy only where they provide a clear numerical benefit.
- Use FastAPI for the backend API.
- Use React and TypeScript for the HMI.
- Use PostgreSQL/TimescaleDB for persistent data.
- Use Docker Compose for initial deployment.
- Use pytest for backend tests and Playwright for frontend end-to-end tests.
- Pin dependencies and use reproducible builds.
- Use structured logging.
- Handle exceptions explicitly.
- Never swallow errors silently.
- Never use placeholder implementations that appear operational.
- Mark incomplete features clearly as NOT IMPLEMENTED.
- Document every approximation, assumption and model limitation.

## 5. Plugin rules

Every plugin must:
- Declare a unique identifier, version and supported plugin API version.
- Declare its category, capabilities and dependencies.
- Validate its configuration before starting.
- Implement the required standardized interface.
- Provide unit tests.
- Provide compatibility information.
- Fail safely if initialization or runtime execution fails.
- Be disabled by default unless explicitly enabled in a simulation configuration.
- Never execute arbitrary untrusted code without an approved trust and isolation model.

Do not dynamically load arbitrary files from user-provided paths.

## 6. Simulation rules

- Use integer simulation ticks or another deterministic time representation.
- Never rely on uncontrolled wall-clock timing for simulated physics.
- Make simulation time distinct from wall-clock time.
- Support pause, resume, step, reset and deterministic replay.
- Seed random processes.
- Validate the numerical stability of models.
- Define execution intervals and ordering explicitly.
- Record simulation configuration and model versions with every run.
- Do not claim hard real-time performance on ordinary desktop operating systems.

## 7. Development workflow

For every task:

1. Inspect the repository and relevant documentation.
2. Summarize the current architecture and relevant existing behavior.
3. Identify assumptions, risks and dependencies.
4. Propose a small implementation plan.
5. Wait for approval if the task changes architecture, safety boundaries, external interfaces or database schemas.
6. Implement only the agreed scope.
7. Add or update tests.
8. Run formatting, linting, type checks and relevant tests.
9. Review the diff for unintended changes.
10. Update documentation.
11. Report files changed, tests run, results, limitations and outstanding risks.

Do not rewrite unrelated modules. Do not delete tests to make a build pass. Do not weaken assertions to hide defects. Do not mark a task complete if tests were not run.

## 8. Definition of done

A feature is complete only when:
- Its implementation exists.
- Its interfaces and configuration are documented.
- Unit tests pass.
- Relevant integration tests pass.
- Error cases are tested.
- Safety implications have been reviewed.
- No known failing tests have been hidden.
- Its limitations are documented.
- The application still starts successfully.

## 9. Git rules

- Work on a feature branch.
- Make small, descriptive commits.
- Never force-push or rewrite shared history.
- Never commit secrets, credentials, private keys or real equipment connection details.
- Keep `.env` files out of version control.
- Review the diff before committing.
- Do not merge a task with failing tests.

## 10. Required response format

At the end of every task, report:

1. Objective and scope.
2. Design decisions.
3. Files created or modified.
4. Tests added.
5. Commands executed and their actual results.
6. Safety considerations.
7. Known limitations.
8. Remaining work.
9. Whether the task's acceptance criteria passed.

Do not claim that something works unless it has been tested or clearly identify it as unverified.