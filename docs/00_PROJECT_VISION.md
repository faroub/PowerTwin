# PowerTwin — Project Vision & Operational Modes

## 1. Executive Summary

**PowerTwin** is a modular, high-fidelity Battery Energy Storage System (BESS) simulator and emulator platform engineered for industrial (Commercial & Industrial - C&I) and utility-scale energy storage applications. 

The platform serves as a digital twin foundation, supporting plant design, control logic verification, energy market strategy simulation, grid service validation, controller-in-the-loop (CIL) testing, and long-term battery degradation and warranty analysis.

---

## 2. Project Mission & Objectives

The core mission of PowerTwin is to provide an open, modular, deterministic, and safe software environment capable of accurately modeling physical and operational behaviors across all tiers of a modern BESS plant:

1. **Electro-Thermal Battery Models**: Cell, module, rack, and container-level voltage, state-of-charge (SoC), state-of-health (SoH), internal resistance, heat generation, and cooling/HVAC dynamics.
2. **BMS & Safety Controllers**: Battery Management System logic including cell balancing, voltage/temperature protection thresholds, contactor control, and fault handling.
3. **Power Conversion System (PCS)**: Inverter and converter efficiency curves, active/reactive power dispatch, grid-forming and grid-following dynamics, response times, thermal derating, and switching state simulation.
4. **Balance of Plant (BoP)**: Transformers, medium/high voltage switchgear, protection relays, HVAC systems, auxiliary loads, and Point of Interconnection (POI) metering.
5. **Control Hierarchy**: Local Equipment Controllers, Power Plant Controller (PPC), and Energy Management System (EMS).
6. **Grid & Market Scenarios**: POI grid voltage and frequency fluctuations, synthetic grid disturbances, frequency regulation scenarios, peak shaving, and energy arbitrage dispatch.
7. **Extensibility & Plugins**: Vendor-specific equipment models and custom control algorithms loaded dynamically via a safe, isolated plugin interface.

---

## 3. Operational Modes & System Boundaries

PowerTwin strictly enforces clear operational boundaries across three primary deployment modes.

```
+-----------------------------------------------------------------------------------+
|                                  POWERTWIN PLATFORM                               |
|                                                                                   |
|  +---------------------+   +--------------------------+   +--------------------+  |
|  |  SIMULATION ONLY    |   | CONTROLLER-IN-THE-LOOP   |   | HARDWARE-IN-LOOP   |  |
|  |     (DEFAULT)       |   |          (CIL)           |   |       (HIL)        |  |
|  |                     |   |                          |   | (FUTURE/CONTROLLED)|  |
|  | Pure Software Stack |   | External Soft/Hard PPC   |   | Real Inverters/BMS |  |
|  | Simulated Physics   |   | Connected via Modbus/    |   | Connected via DAQ/ |  |
|  | Simulated Controller|   | DNP3 Emulators           |   | Approved I/O       |  |
|  +---------------------+   +--------------------------+   +--------------------+  |
+-----------------------------------------------------------------------------------+
```

### Mode 1: SIMULATION ONLY (Default Mode)
- **Scope**: 100% pure software simulation execution within an isolated runtime environment.
- **Physics & Control**: Battery electro-thermal dynamics, PCS, switchgear, grid, BMS, PPC, and EMS are all executed internally inside the central simulation engine.
- **Hardware Interaction**: Absolutely **ZERO** connection, discovery, scanning, commanding, or network traffic to physical industrial hardware or external interfaces.
- **Clock**: Synchronized strictly to an internal deterministic tick-based simulation clock (decoupled from wall-clock time).

### Mode 2: CONTROLLER-IN-THE-LOOP (CIL)
- **Scope**: The physical BESS plant and equipment controllers (BMS/PCS) are simulated by the PowerTwin simulation engine, while an external physical or software controller (e.g., third-party PPC or EMS) executes independently.
- **Interface**: External controllers communicate with PowerTwin via protocol emulators (Modbus TCP, DNP3, IEC 60870-5-104, SunSpec).
- **Safety Boundary**: Read-only monitoring by default; external writable command interfaces require explicit user authorization and configuration.

### Mode 3: HARDWARE-IN-THE-LOOP (HIL) (Future Phase — Strictly Controlled)
- **Scope**: Physical hardware components (e.g., real BMS microcontrollers, physical PCS control boards, or power hardware via amplifier interfaces) connected to the simulation engine.
- **Safety Rule**: **STRICTLY PROHIBITED IN INITIAL RELEASES.** Requires a dedicated, independently audited, and approved hardware integration task force before any low-level hardware driver or physical I/O interface may be compiled or enabled.

---

## 4. Digital Twin Capabilities

1. **Model Calibration**: Parameter fitting using real field operational data to align simulated cell OCV curves, internal resistances, and thermal capacitance with actual site measurements.
2. **Degradation & Warranty Analysis**: Multi-year simulation accelerating capacity fade (SEI layer growth, lithium plating) and power fade under diverse thermal and dispatch profiles to evaluate warranty compliance.
3. **Financial & Grid Scenario Testing**: Evaluating revenue streams and degradation costs across market scenarios (e.g., frequency response vs. arbitrage).
