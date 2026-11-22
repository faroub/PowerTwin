# PowerTwin — Modular Industrial BESS Simulator & Emulator Platform

> [!CAUTION]
> **SAFETY & SIMULATION-ONLY DISCLAIMER**:
> PowerTwin operates strictly in **SIMULATION ONLY** mode (`SIMULATION_ONLY = True`).
> It is a software simulation, emulation, and Controller-in-the-Loop (CIL) testing platform for power systems engineering, control algorithm verification, and SCADA Web HMI testing.
> It is **NOT** certified battery safety protection hardware or a live BESS control system.

---

## 1. Executive Summary

PowerTwin is a modular, high-performance industrial Energy Storage System (BESS) simulator and emulator platform. It features a $100\text{ Hz}$ integer nanosecond tick simulation engine, 12 standardized domain equipment interfaces, a 3-tier control hierarchy (Equipment Controller, PPC, EMS), a SCADA Web HMI, an isolated Modbus TCP CIL protocol gateway, and vendor equipment plugins for CATL, Tesla, SMA, and Sungrow systems.

---

## 2. Key Platform Features

- **100 Hz Deterministic Simulation Engine**: Integer nanosecond clock ($10\text{ ms}$ tick step), 6-phase DAG scheduler, seeded random number generator (`seed=42`), bit-exact replay determinism, and full state snapshot serialization.
- **Single Equipment Ownership Model**: Every configured asset corresponds to exactly ONE authoritative runtime model instance across scheduler, control hierarchy, electrical network, and historian.
- **3-Tier Control Architecture**:
  - **Layer A Equipment Controller**: State-machine device startup/shutdown sequencing with command result verification and automatic rollback.
  - **Layer B Power Plant Controller (PPC)**: POI active/reactive power regulation, apparent power circle clamping ($P^2 + Q^2 \le S_{\text{max, eff}}^2$), and capability-aware unit allocation.
  - **Layer C Energy Management System (EMS)**: Multi-container power limit aggregation, dispatch feasibility checking, and frequency response droop control.
- **Isolated Modbus TCP CIL Protocol Gateway**: Bound strictly to loopback (`127.0.0.1:5020`), read-only telemetry registers (`0x0000`–`0x000C`), command write registers (`0x0064`–`0x006C`) routed to plant EMS dispatch loop, watchdog heartbeat tracking ($5\text{s}$ timeout).
- **19-View SCADA Web HMI**: React 18 + TypeScript SCADA dashboard with interactive Single-Line Diagram (SLD), real-time telemetry display, and explicit **"SIMULATED DATA ONLY"** labeling.
- **Zero Silent Data Loss Historian**: Thread-safe in-memory ring buffer with emergency append-only disk overflow fallback.

---

## 3. Quick Start & Local Execution

### Backend Tests & Verification
```bash
# Verify formatting
PYTHONPATH=. ruff format --check backend plugins tests

# Run linter
PYTHONPATH=. ruff check backend plugins tests

# Run static type checker
PYTHONPATH=. mypy --config-file backend/pyproject.toml backend plugins

# Run complete pytest suite
PYTHONPATH=. pytest
```

### Frontend Web HMI Build & Tests
```bash
cd frontend

# Run TypeScript type check
npm run lint

# Run Vitest component tests
npm test

# Build production Web HMI bundle
npm run build
```

---

## 4. Documentation Index

- [docs/POWER_TWIN_IMPLEMENTATION_STATUS.md](file:///home/faroub/Documents/Projects/PowerTwin/docs/POWER_TWIN_IMPLEMENTATION_STATUS.md)
- [docs/POWER_TWIN_REQUIREMENTS_TRACEABILITY.md](file:///home/faroub/Documents/Projects/PowerTwin/docs/POWER_TWIN_REQUIREMENTS_TRACEABILITY.md)
- [docs/POWER_TWIN_KNOWN_LIMITATIONS.md](file:///home/faroub/Documents/Projects/PowerTwin/docs/POWER_TWIN_KNOWN_LIMITATIONS.md)
- [docs/POWER_TWIN_REMAINING_WORK.md](file:///home/faroub/Documents/Projects/PowerTwin/docs/POWER_TWIN_REMAINING_WORK.md)
- [docs/20_SYSTEM_INTEGRATION_AND_RELEASE_READINESS_REPORT.md](file:///home/faroub/Documents/Projects/PowerTwin/docs/20_SYSTEM_INTEGRATION_AND_RELEASE_READINESS_REPORT.md)
- [docs/CI_CD_GUIDE.md](file:///home/faroub/Documents/Projects/PowerTwin/docs/CI_CD_GUIDE.md)
