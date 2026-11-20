# PowerTwin — Generic Battery and BMS Model Specification (WP04A)

## 1. Overview & Operational Scope

This document specifies the physics, energy balance equations, sign conventions, BMS protection limiters, and structural hierarchy for the WP04A Battery & BMS simulation models.

The WP04A battery system is an **energy-balanced operational model** designed for Energy Management System (EMS), Power Plant Controller (PPC), and equipment-controller software integration and testing. It is **NOT** an electrochemical cell model.

---

## 2. Documented Sign Conventions

PowerTwin enforces a uniform electrical sign convention across all models:

- **Active Power ($P$)**:
  - $+P$ (Positive Power): **DISCHARGING** (Battery delivering active power into the plant/grid).
  - $-P$ (Negative Power): **CHARGING** (Battery absorbing active power from the plant/grid).
- **DC Current ($I$)**:
  - $+I$ (Positive Current): **DISCHARGE CURRENT** leaving battery terminals.
  - $-I$ (Negative Current): **CHARGE CURRENT** entering battery terminals.

---

## 3. Mathematical Energy Balance & Efficiency Equations

### 3.1 Discharge State ($P_{\text{bat}} > 0$)
When discharging, chemical energy drawn from internal battery cells includes efficiency losses:

$$P_{\text{chem}} = \frac{P_{\text{bat}}}{\eta_{\text{discharge}}}$$

$$\Delta E_{\text{chem\_wh}} = \frac{P_{\text{chem}} \cdot \Delta t_{\text{s}}}{3600}$$

$$\Delta \text{SoC}_{\text{dis\_pct}} = - \frac{\Delta E_{\text{chem\_wh}}}{E_{\text{nom\_wh}}} \cdot 100\%$$

Power loss dissipated as heat:

$$P_{\text{loss\_w}} = P_{\text{chem}} - P_{\text{bat}}$$

### 3.2 Charge State ($P_{\text{bat}} < 0$)
When charging, chemical energy stored into internal battery cells accounts for charge efficiency:

$$P_{\text{chem}} = |P_{\text{bat}}| \cdot \eta_{\text{charge}}$$

$$\Delta E_{\text{chem\_wh}} = \frac{P_{\text{chem}} \cdot \Delta t_{\text{s}}}{3600}$$

$$\Delta \text{SoC}_{\text{ch\_pct}} = + \frac{\Delta E_{\text{chem\_wh}}}{E_{\text{nom\_wh}}} \cdot 100\%$$

Power loss dissipated as heat:

$$P_{\text{loss\_w}} = |P_{\text{bat}}| - P_{\text{chem}}$$

### 3.3 Round-Trip Efficiency (RTE)
Total round-trip efficiency is defined as:

$$\eta_{\text{RTE}} = \eta_{\text{charge}} \cdot \eta_{\text{discharge}}$$

For $\eta_{\text{charge}} = 0.97$ and $\eta_{\text{discharge}} = 0.97$, total RTE is $\approx 94.09\%$.

### 3.4 Auxiliary Power Consumption
Continuous container auxiliary loads ($P_{\text{aux}}$) consume energy continuously from battery storage:

$$\Delta \text{SoC}_{\text{aux\_pct}} = \frac{P_{\text{aux}} \cdot \Delta t_{\text{s}}}{3600 \cdot E_{\text{nom\_wh}}} \cdot 100\%$$

---

## 4. BMS Limits & Derating Rules

The Master BMS continuously evaluates dynamic Charge Current Limits ($\text{CCL}$) and Discharge Current Limits ($\text{DCL}$):

1. **SoC Limit Clamping**:
   - If $\text{SoC} \ge \text{SoC}_{\text{max\_pct}}$ ($95\%$), $\text{CCL} = 0\text{ A}$.
   - If $\text{SoC} \le \text{SoC}_{\text{min\_pct}}$ ($5\%$), $\text{DCL} = 0\text{ A}$.
2. **Thermal Derating & Cutoff**:
   - Optimal operating temperature range: $5^\circ C \le T \le 45^\circ C$.
   - Outside optimal window ($T > 45^\circ C$ or $T < 5^\circ C$), current limits derate by $50\%$.
   - Hard trip boundaries: $T \ge 60^\circ C$ or $T \le -10^\circ C$ trips BMS (`OVER_TEMP_FAULT` / `UNDER_TEMP_FAULT`), opens contactors, and safe-parks system.

---

## 5. Structural Hierarchy

The model supports configurable hierarchy mapping:
$$\text{Plant} \rightarrow \text{Container} \rightarrow \text{Master BMS} \rightarrow \text{Rack} \rightarrow \text{Module} \rightarrow \text{Cell}$$

In the initial release, energy and power calculations are aggregated at the Plant/Container tier while preserving physical cell and module count specifications.

---

## 6. Documented Assumptions & Limitations

1. **Lumped Thermal Approximation**: Container temperature uses a single-node lumped thermal mass model ($C_{\text{thermal}}$). Spatial temperature gradients across individual modules or cell hotspots are not modeled in WP04A.
2. **Linear Degradation Approximation**: State of Health (SoH) is represented via simple energy throughput accumulation rather than multi-year SEI layer degradation physics.
3. **ECM Dynamic Voltage Off**: Terminal voltage uses open-circuit voltage (OCV) curve fitting based on SoC ($V = V_{\text{nom}} \cdot (0.85 + 0.30 \cdot \text{SoC})$). Fast RC transient dynamics are provided via the stubbed `EquivalentCircuitModelInterface`.
