# PowerTwin — Control System Specification

## 1. BESS Control Hierarchy

PowerTwin models a hierarchical control architecture reflecting real-world industrial and utility-scale BESS deployments:

```
+-------------------------------------------------------------------------------+
|                      ENERGY MANAGEMENT SYSTEM (EMS)                           |
|       - High-Level Dispatch, Peak Shaving, Arbitrage, Market Interface         |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
|                      POWER PLANT CONTROLLER (PPC)                             |
|       - POI Active/Reactive Power Control, Frequency Droop, Volt-VAR          |
+-------------------------------------------------------------------------------+
                   |                                           |
                   v                                           v
+---------------------------------------+   +-----------------------------------+
|      MASTER BMS CONTROLLER            |   |       PCS INVERTER CONTROLLER     |
| - Rack Limits, Protection Interlocks  |   | - Real/Reactive Power Actuation   |
+---------------------------------------+   +-----------------------------------+
                   |                                           |
                   v                                           v
+---------------------------------------+   +-----------------------------------+
|      RACK BMS & CELL BALANCING        |   |   SWITCHGEAR & TRANSFORMER TAP    |
+---------------------------------------+   +-----------------------------------+
```

---

## 2. Priority Override & Safety Interlock Chain

Control actions are strictly evaluated according to a hardcoded priority hierarchy:

1. **Level 0 (Highest): Physical / E-Stop Interlocks**: Manual E-Stop, Fire Suppression activation, Critical Voltage/Temp trip. Immediately opens MV switchgear and PCS contactors. Cannot be overridden by software.
2. **Level 1: BMS Protection Limits**: Maximum Charge Current Limit (CCL) and Discharge Current Limit (DCL) enforced dynamically based on cell voltage, temperature, and SoC.
3. **Level 2: PPC Grid Code Limits**: Inverter apparent power ($S_{\text{max}}$) clipping, POI ramp rate limiters.
4. **Level 3: Operator Direct Setpoints**: Direct manual overrides from local HMI (requires elevated operator role).
5. **Level 4 (Lowest): EMS Schedule**: Automatic economic dispatch profiles.

---

## 3. Operational Modes & Control Algorithms

### 3.1 Frequency Regulation (P-f Droop & FFR)
- **Droop Curve**: Active power output $P_{\text{req}}$ adjusts dynamically based on POI grid frequency deviation $\Delta f = f_{\text{grid}} - f_{\text{nominal}}$:

$$P_{\text{droop}} = - \frac{P_{\text{rated}}}{R} \cdot \frac{f_{\text{grid}} - f_{\text{nominal}}}{f_{\text{nominal}}}$$

where $R$ is the droop percentage (e.g. $2\% - 5\%$) and a configurable deadband (e.g. $\pm 0.03\text{ Hz}$) is enforced.

### 3.2 Volt-VAR Control
- Adjusts reactive power output $Q_{\text{req}}$ as a function of POI voltage deviation $V_{\text{grid}} - V_{\text{nominal}}$ according to a configurable multi-point piecewise linear VAR curve.

### 3.3 Peak Shaving & Load Following
- Monitors POI site demand and commands BESS discharge when total site load exceeds a defined threshold $P_{\text{peak\_limit}}$, charging when load falls below $P_{\text{offpeak\_limit}}$.

### 3.4 Scheduled Dispatch & Arbitrage
- Executes time-of-use active/reactive power setpoints provided via daily schedule profiles or market API commands.

---

## 4. Rate Limiters & Anti-Windup Protection

- **Ramp Rate Limiters**: All power setpoint transitions must be bounded by a maximum rate of change (e.g. $\text{Ramp}_{\text{max}} = 10\text{ MW/s}$) to prevent electrical stress on grid assets and inverter switches.
- **Integrator Anti-Windup**: Closed-loop PI controllers in PPC (for POI voltage/power regulation) enforce strict clamping on integral state accumulators when PCS capability limits ($P_{\text{max}}, Q_{\text{max}}$) are reached.
