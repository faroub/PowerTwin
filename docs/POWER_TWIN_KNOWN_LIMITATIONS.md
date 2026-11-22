# PowerTwin — Platform Known Limitations & Engineering Disclaimers

## 1. Explicit Safety and Certification Disclaimer

> [!CAUTION]
> **SIMULATION & CIL EMULATION DISCLAIMER**:
> PowerTwin is a software simulation, emulation, and Controller-in-the-Loop (CIL) testing platform.
> It is **NOT** certified battery safety protection hardware, a physical inverter, or a replacement for real BESS equipment.
> Direct connection of this software to physical high-voltage BESS contactors or live industrial power networks without formal physical laboratory authorization is strictly prohibited.

---

## 2. Technical & Physical Model Limitations

### 1. Simulation Engine & Time Resolution
- **Fixed Step Frequency**: The simulation engine operates on a fixed integer nanosecond tick clock with a default step size of $10\text{ ms}$ ($100\text{ Hz}$ execution frequency).
- **Phasor-Domain Scope**: Sub-millisecond electromagnetic transient (EMT) phenomena, high-frequency PWM switching harmonics ($> 1\text{ kHz}$), and sub-microsecond lightning surge events are beyond the scope of $100\text{ Hz}$ phasor-domain simulation.

### 2. Battery & BMS Physical Models
- **Equivalent Circuit Formulation**: Battery cell dynamics utilize an energy-balanced Equivalent Circuit Model (ECM) with open-circuit voltage (OCV) vs. SoC interpolation and internal resistance ($R_{\text{int}}$) losses.
- **Lumped Thermal Mass**: Thermal dynamics assume a lumped container heat capacity ($J/\text{^\circ C}$) with convective cooling. Spatial 3D cell-to-cell thermal gradients and CFD coolant fluid dynamics are not computed.
- **BMS Protection Logic**: The master BMS model simulates protection threshold logic for control loop testing. It does not replace certified hardware BMS microcontrollers or hardwired analog safety relays.

### 3. PCS Inverter Models
- **Capability Circle & Ramp Limiter Scope**: Inverters model steady-state $P/Q$ capability circle clamping ($P^2 + Q^2 \le S_{\text{max, eff}}^2$), $P/Q$ ramp rate limits, and IGBT heatsink thermal mass.
- **Semiconductor Switching**: Microsecond IGBT gate turn-on/turn-off times, dead-time distortion, and DC-bus voltage ripple are not computed.

### 4. Electrical Network & Grid Physics
- **Single-Phase Equivalent Phasor Solver**: The electrical network calculates balanced 3-phase power flow using `SimplePhasorPowerFlowSolver`.
- **Asymmetrical & Unbalanced Grids**: Phase unbalance (e.g. single-phase line-to-ground faults) and harmonic distortion ($THD_V$) are not modeled in v1.0.0.

### 5. CIL Protocol Gateway & Network Scope
- **Loopback Isolation**: The Modbus TCP CIL server is bound strictly to loopback (`127.0.0.1:5020`).
- **Protocol Support**: v1.0.0 implements Modbus TCP holding register maps. OPC UA and MQTT gateway adapters exist as abstract interface specifications for future release phases.
