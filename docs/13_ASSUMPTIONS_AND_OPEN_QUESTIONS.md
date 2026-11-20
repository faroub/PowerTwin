# PowerTwin — Assumptions, Technical Risks, and Open Questions

## 1. Explicit Technical Assumptions

1. **Host Operating System**: Initial simulation-only releases target standard 64-bit Linux (Ubuntu 22.04 LTS / 24.04 LTS) and Docker Compose environments without requiring real-time kernel patches (RT-PREEMPT).
2. **Simulation Time Step**: Default simulation resolution is fixed at $\Delta t = 10\text{ ms}$ ($100\text{ Hz}$ update rate), which is sufficient for electro-thermal dynamics and secondary grid frequency response simulation.
3. **Equivalencing**: Large battery containers (e.g. 10,000 cells) are modeled using lumped Equivalent Circuit Models (ECM) aggregated at the rack and module level to maintain real-time performance bounds.
4. **Parameter Source Labeling**: All default cell parameters (e.g. 3.2V 280Ah LFP cell data) provided in template configuration files are explicitly designated as `is_illustrative: true` until calibrated against official manufacturer datasheets.

---

## 2. Technical Risk Matrix & Mitigation Strategies

| Risk Description | Severity | Likelihood | Proposed Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **R-001: Numerical Instability in Stiff Models** | High | Medium | Implement adaptive step-size ODE solvers (RK4/Implicit Euler) with fallback bounds checking and NaN detection. |
| **R-002: Real-time Performance Bottleneck at Scale** | Medium | Medium | Benchmark 100 MW plant models early; optimize inner battery tick loops using NumPy vectorized array operations or C extensions (Cython/Rust) if needed. |
| **R-003: Accidental Hardware Integration Risk** | Critical | Low | Enforce hardcoded `hardware_mode_enabled = False` default, strictly segregate physical driver modules, and bind protocol servers to `127.0.0.1`. |
| **R-004: Ingress Command Overflow / Crash** | High | Low | Enforce strict Pydantic range checking, rate limiters, and safety interlocks at the protocol ingress boundary. |

---

## 3. Prioritized Unresolved Decisions & Open Questions

| Priority | Issue / Decision Required | Options / Tradeoffs | Action Required |
| :--- | :--- | :--- | :--- |
| **P1** | **Plugin Sandboxing Isolation Model** | Option A: In-process Python abstract base class (Fast, lightweight, shared memory).<br>Option B: Out-of-process IPC / gRPC plugins (High security & isolation, slight IPC latency). | Evaluate latency overhead of gRPC vs. in-process execution for 100 Hz tick rates. |
| **P2** | **TimescaleDB Compression vs Ingest Performance** | Option A: Write directly to hypertable per tick.<br>Option B: In-memory ring buffer batching before DB flush. | Run load tests to determine DB write latency impact on tick loop. |
| **P3** | **Hardware-in-the-Loop DAQ Card Abstraction** | Select low-level I/O library interface for future Phase 5 HIL tasks. | Postpone decision until Phase 5 safety audit. |
