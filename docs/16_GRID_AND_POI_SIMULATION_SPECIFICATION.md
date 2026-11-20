# PowerTwin — Grid and Point of Interconnection (POI) Simulation Specification (WP04C)

## 1. Overview & Operational Scope

This document specifies the synthetic grid model, Point of Interconnection (POI) boundary meter, grid disturbance engines, and power flow interfaces for WP04C.

---

## 2. Documented Equations & Sign Conventions

- **POI Flow Direction**:
  - $+P_{\text{poi}}$ (Positive Active Power) = **EXPORTING** to AC Grid (BESS Discharging).
  - $-P_{\text{poi}}$ (Negative Active Power) = **IMPORTING** from AC Grid (BESS Charging).
  - Flow Direction State: `EXPORTING` ($P > 0.001\text{ W}$), `IMPORTING` ($P < -0.001\text{ W}$), `ZERO`.

- **Grid Impedance Voltage Shift Equation**:
  The POI grid line voltage shift resulting from active and reactive power injection across grid Thevenin impedance ($R_{\text{grid}} + j X_{\text{grid}}$) is calculated using simplified RMS phasor power flow:

$$\Delta V_{\text{grid}} \approx \frac{P_{\text{poi}} \cdot R_{\text{grid}} + Q_{\text{poi}} \cdot X_{\text{grid}}}{V_{\text{nom\_v}}}$$

$$V_{\text{poi\_actual}} = V_{\text{grid\_nominal}} + \Delta V_{\text{grid\_disturbance}} + \Delta V_{\text{grid}}$$

---

## 3. Grid Disturbances Engine

The grid model supports 6 configurable disturbance types:

1. **`FREQUENCY_STEP`**: Instantaneous frequency step ($\pm \Delta f\text{ Hz}$).
2. **`FREQUENCY_RAMP`**: Linear frequency ramp rate ($df/dt\text{ Hz/s}$ over duration $T$).
3. **`VOLTAGE_STEP`**: Instantaneous voltage step ($\pm \Delta V\text{ V}$).
4. **`VOLTAGE_RAMP`**: Linear voltage ramp rate ($dV/dt\text{ V/s}$ over duration $T$).
5. **`GRID_DISCONNECTION`**: Trips grid breaker, sets state to `DISCONNECTED` / `ISLANDED`, and zeroes POI power flow.
6. **`GRID_RECONNECTION`**: Restores grid breaker state back to `GRID_CONNECTED`.

---

## 4. POI Boundary Monitoring & Alarms

The POI model monitors boundary power, voltage, and frequency against configurable operational limits:

- **Export Power Limit**: $+50\text{ MW}$ (Triggers `POI_EXPORT_LIMIT_EXCEEDED` warning).
- **Import Power Limit**: $-50\text{ MW}$ (Triggers `POI_IMPORT_LIMIT_EXCEEDED` warning).
- **Voltage High/Low Limits**: $13.8\text{ kV} \pm 5\%$ ($14.49\text{ kV}$ / $13.11\text{ kV}$) (Triggers `POI_OVER_VOLTAGE` / `POI_UNDER_VOLTAGE`).
- **Frequency High/Low Limits**: $60.0\text{ Hz} \pm 0.5\text{ Hz}$ ($60.5\text{ Hz}$ / $59.5\text{ Hz}$) (Triggers `POI_OVER_FREQ` / `POI_UNDER_FREQ`).

---

## 5. Interface for Future Distribution Solvers (PandaPower / OpenDSS)

PowerTwin defines `PowerFlowSolverInterface` to decouple network power flow solutions from the core simulation engine:

- **`SimplePhasorPowerFlowSolver`**: Steady-state phasor solver implemented for WP04C.
- **`PandaPowerOpenDSSInterfaceStub`**: Extensible interface definition for future WP06 distribution network integrations (Pandapower / OpenDSS multi-node AC power flow).
