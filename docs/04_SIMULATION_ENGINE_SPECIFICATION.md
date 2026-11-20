# PowerTwin — Simulation Engine Specification

## 1. Core Design & Time Representation

The PowerTwin simulation engine provides a deterministic, tick-based environment for modeling complex multi-domain BESS dynamics.

### 1.1 Integer Simulation Ticks
- **Time Unit**: Simulation time is represented internally as an unsigned 64-bit integer representing simulation nanoseconds (`uint64` in nanoseconds).
- **Default Tick Step ($\Delta t$)**: Configurable fixed step (default: $10\text{ ms} = 10,000,000\text{ ns}$, corresponding to a $100\text{ Hz}$ update frequency).
- **Time Invariant**: Wall-clock time **NEVER** directly dictates model physics. Model equations operate strictly on the simulation tick step $\Delta t$.

```
+-------------------------------------------------------------------------------+
|                       CENTRAL SIMULATION TICK TICK LOOP                       |
|                                                                               |
|  Current Tick: T_sim = T_sim + Delta_T_ns                                     |
|                                                                               |
|  [Phase 1] Grid/Env Update  ->  [Phase 2] Controllers (BMS/PPC/EMS)            |
|                                          |                                    |
|  [Phase 5] Telemetry Log    <-  [Phase 4] Electro-Thermal  <- [Phase 3] PCS      |
+-------------------------------------------------------------------------------+
```

---

## 2. Tick Execution Pipeline & DAG Ordering

To prevent implicit execution order dependencies and race conditions, each tick executes models in a strictly ordered Directed Acyclic Graph (DAG) phase sequence:

1. **Phase 1: Environment & External Inputs**: Update grid frequency, POI voltage profile, ambient temperature, and external scenario driver scripts.
2. **Phase 2: High-Level & Mid-Level Controllers**: Execute EMS algorithms, PPC regulation loops, and Master BMS protection logic.
3. **Phase 3: Actuators & Power Conversion**: Update PCS inverter switching/dispatch outputs, transformer tap positions, and switchgear breaker states.
4. **Phase 4: Physical Battery Dynamics**: Calculate battery equivalent circuit voltages, currents, state-of-charge, Joule heating, and thermal diffusion equations.
5. **Phase 5: Balance of Plant & Thermal Controls**: Calculate HVAC heat extraction, auxiliary container power draw, and total net POI power flow.
6. **Phase 6: State Snapshot & Telemetry Dispatch**: Capture engine state snapshot, check alarm thresholds, and stream telemetry to TimescaleDB and HMI WebSockets.

---

## 3. Simulation Lifecycle Controls

The engine exposes standard execution control primitives:
- `start()`: Begin tick execution loop.
- `pause()`: Freeze tick accumulation immediately at the boundary of the current tick.
- `resume()`: Continue tick execution from the exact paused tick.
- `step(num_ticks: int = 1)`: Execute exactly `num_ticks` iterations and return engine state.
- `reset(config_override: Optional[dict] = None)`: Reset simulation tick `T_sim = 0`, restore initial state values, and re-seed random engines.
- `set_speed_factor(multiplier: float)`: Adjust target wall-clock pacing ($0.1\times$ to $100\times$, or `0.0` for maximum headless execution speed).

---

## 4. Determinism & Replayability

To guarantee identical simulation results across different hardware hosts:
1. **Seeded Pseudo-Random Generators**: All stochastic elements (e.g., sensor noise, grid frequency fluctuation) must use dedicated NumPy random generators initialized with an explicit seed specified in the simulation config (`random_seed: int = 42`).
2. **State Serialization**: Engine state at tick $N$ is fully serializable into a JSON/Pydantic snapshot schema.
3. **Replay Validation**: Re-running a scenario with the same initial configuration and seed must produce bit-exact telemetry output across all ticks.

---

## 5. Numerical Stability & Integration Methods

Battery thermal capacitance dynamics and equivalent circuit models (ECM) involve differential equations of varying time constants:

$$\frac{d V_{C1}}{dt} = \frac{I_{bat}}{C_1} - \frac{V_{C1}}{R_1 C_1}$$

$$\frac{d T_{container}}{dt} = \frac{\dot{Q}_{gen} - \dot{Q}_{hvac}}{m \cdot c_p}$$

- **Integration Scheme**:
  - Default: **Explicit Forward Euler** for fast execution when $\Delta t \le \min(\tau) / 5$.
  - Adaptive: **4th-Order Runge-Kutta (RK4)** or **Implicit Backward Euler** for stiff sub-models (e.g. fast switching dynamics or low thermal mass components).
- **Stability Safeguards**: If calculated state values ($V, I, T, SoC$) exceed physical bounds or output NaN/Inf, the engine immediately flags a `NUMERICAL_INSTABILITY_FAULT`, logs the snapshot, and pauses execution safely.
