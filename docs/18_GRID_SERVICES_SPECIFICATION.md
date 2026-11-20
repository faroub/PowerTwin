# PowerTwin — Modular Grid Services Specification (WP09)

## 1. Architecture & Separation of Concerns

PowerTwin enforces clean separation between Grid Service calculations and Power Plant Controller (PPC / Layer B) execution:

```
+-------------------------------------------------------------------------------+
|                      GRID SERVICE PLUGIN (MODULE)                             |
|  - Calculates requested P_req and Q_req setpoints                             |
|  - Evaluates service availability & compliance performance score (0.0 - 1.0) |
|  - NEVER issues direct equipment actuation or Modbus commands                 |
+-------------------------------------------------------------------------------+
                                       | Requested P_req, Q_req
                                       v
+-------------------------------------------------------------------------------+
|                      POWER PLANT CONTROLLER (PPC - LAYER B)                   |
|  - Validates feasibility against plant S_max, ramp limits, & interlocks       |
|  - Allocates feasible setpoints to active PCS units                           |
+-------------------------------------------------------------------------------+
```

---

## 2. Seven Standardized Grid Service Plugins

1. **Energy Arbitrage (`energy_arbitrage_v1`)**: Scheduled time-of-use peak discharge (+P) and off-peak charge (-P).
2. **Frequency Containment Reserve - FCR (`fcr_v1`)**: Primary frequency control providing fast proportional response to grid frequency deviations ($P = - \frac{P_{\text{rated}}}{\text{droop\%}} \cdot \frac{\Delta f}{f_{\text{nom}}}$).
3. **Automatic Frequency Restoration Reserve - aFRR (`aFRR_v1`)**: Secondary frequency control reacting to AGC setpoint signals.
4. **Manual Frequency Restoration Reserve - mFRR (`mFRR_v1`)**: Tertiary control executing TSO manual dispatch orders.
5. **Voltage & Volt-VAR Support (`volt_var_support_v1`)**: Reactive power support ($Q$) responding to POI voltage deviations.
6. **Peak Shaving (`peak_shaving_v1`)**: Demand limiting discharging BESS when facility load exceeds threshold.
7. **Renewable Power Smoothing (`renewable_smoothing_v1`)**: Absorbing/injecting power to damp solar and wind generation ramps.

---

## 3. Compliance & Qualification Disclosure

> [!IMPORTANT]
> **DISCLOSURE OF COMPLIANCE STATUS**:
> The 7 grid services implemented in PowerTwin are **FUNCTIONAL SIMULATION DEMONSTRATIONS** designed for software testing, educational modeling, and control system verification.
> 
> They do **NOT** claim certified compliance with specific regional TSO/DSO grid-code specifications (e.g. ENTSO-E FCR prequalification, CAISO Regulation, PJM RegA/RegD, or NERC BAL-001) until formal qualification test suites are validated against official TSO test harnesses.
