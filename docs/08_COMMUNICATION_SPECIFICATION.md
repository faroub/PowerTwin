# PowerTwin — Communication Specification

## 1. Overview

PowerTwin provides industrial protocol emulators to enable seamless Controller-in-the-Loop (CIL) integration with third-party PPC, EMS, and SCADA systems while maintaining strict security and command validation boundaries.

---

## 2. Supported Industrial Protocol Emulators

```
+-------------------------------------------------------------------------------+
|                       EXTERNAL CONTROLLER / SCADA                             |
+-------------------------------------------------------------------------------+
       |                         |                        |
       | Modbus TCP              | DNP3 (IEEE 1815)       | SunSpec Modbus
       v                         v                        v
+-------------------------------------------------------------------------------+
|                      POWERTWIN PROTOCOL EMULATION LAYER                       |
|  - Address Mapping Table                                                      |
|  - Strict Command Ingress Range & Rate Limiter Boundary                       |
+-------------------------------------------------------------------------------+
                                       |
                                       v Validated Telemetry / Commands
+-------------------------------------------------------------------------------+
|                         CENTRAL SIMULATION ENGINE                             |
+-------------------------------------------------------------------------------+
```

### 2.1 Modbus TCP / RTU Server Emulator
- Maps BESS state variables (voltages, currents, temperatures, SoC, active/reactive power setpoints) to standard Modbus Holding Registers (4x) and Input Registers (3x).
- Supports standard function codes: FC03 (Read Holding), FC04 (Read Input), FC06 (Write Single Register), FC16 (Write Multiple Registers).

### 2.2 DNP3 (IEEE 1815) Server Emulator
- Supports DNP3 Outstation profile providing Analog Inputs, Binary Inputs, Analog Output Controls, and Binary Output Controls.
- Supports unsolicited response generation and event buffer handling for time-tagged SCADA updates.

### 2.3 SunSpec Modbus Interface
- Implements standard SunSpec models: Model 1 (Common), Model 101/103 (Inverter), Model 701 (DER Battery Base Model), Model 704 (DER AC Measurement).

---

## 3. Command Validation & Ingress Safety Boundary

All incoming write requests received via protocol servers or REST API endpoints **MUST** pass through the Command Validation Boundary before affecting simulation state:

```
+-------------------------------------------------------------------------------+
|                       COMMAND VALIDATION BOUNDARY                             |
|                                                                               |
|  1. Timestamp Check  : Rejects commands with timestamp drift > 5000 ms.       |
|  2. Range Validation : Ensures P_req in [P_min, P_max], Q_req in [Q_min, Q_max]|
|  3. Rate Limiter     : Ensures delta_P / delta_t <= Ramp_Rate_Limit.           |
|  4. State Consistency: Rejects "Close Breaker" if Interlock_OK is FALSE.      |
+-------------------------------------------------------------------------------+
```

---

## 4. Hardware Integration Safety Guardrails

- **Default Server State**: All protocol listeners (Modbus server, DNP3 outstation) are bound to `127.0.0.1` and set to `DISABLED` upon initial application installation.
- **Hardware Prohibition**: Protocol emulators act exclusively as **SERVERS** responding to external controllers. They are strictly forbidden from initiating client connection scans, ARP discovery, or automated packet transmission onto physical local networks.
- **Audit Logging**: Every register write or command payload is logged in the `audit_log` with remote IP, timestamp, requested value, and validation outcome.
