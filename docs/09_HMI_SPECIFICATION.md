# PowerTwin — Local Web HMI Specification

## 1. Technology Stack & Core Objectives

The PowerTwin Human-Machine Interface (HMI) is a responsive, web-based control and monitoring dashboard built with **React**, **TypeScript**, and **Tailwind CSS**.

The HMI provides operators and test engineers with real-time plant visibility, interactive single-line diagrams, alarm processing, scenario controls, and historical trend analysis.

---

## 2. Core HMI Views & Features

### 2.1 Executive Overview Dashboard
- Real-time gauge metrics: Net POI Active Power ($MW$), Reactive Power ($MVAR$), Total Plant SoC ($\%$), Average Cell Temperature ($^\circ C$).
- Plant state indicator: Operating State (Standby, Running, Fault, E-Stop), Active Alarms count.
- Dynamic power flow visualization showing energy movement between Battery Containers -> PCS -> Transformer -> POI.

### 2.2 Interactive Single-Line Diagram (SLD) View
- SVG/Canvas-based representation of physical plant topology.
- Real-time color-coded component states:
  - Switchgear Breakers (Green = Closed, Red = Open, Yellow = Fault).
  - PCS Inverters (Active = Blue flow animation, Idle = Grey).
  - Battery Racks (SoC fill levels and thermal hotspots).
- Clicking any SLD element opens an interactive telemetry detail drawer.

### 2.3 Control & Command Panel
- Manual setpoint inputs ($P_{\text{req}}, Q_{\text{req}}$, Power Factor).
- Command action buttons: `Start Plant`, `Stop Plant`, `Trip Breaker`, `Reset Faults`.
- **Safety Rule (Dual-Action Confirmation)**: Any command altering physical plant state requires an explicit confirmation modal displaying requested value vs current limit before dispatching to the API server.

```
+-------------------------------------------------------------------------------+
|                        CONFIRM COMMAND DISPATCH                               |
|                                                                               |
| Action: Set Active Power Setpoint                                             |
| Target: PCS Container 01                                                       |
| New Setpoint: +5.00 MW                                                        |
| Safe Limit  : [-10.00 MW, +10.00 MW]                                           |
|                                                                               |
| [ CANCEL ]                                          [ CONFIRM & DISPATCH ]    |
+-------------------------------------------------------------------------------+
```

### 2.4 Alarm Banner & Event Log View
- Real-time persistent top banner displaying active `CRITICAL` and `FAULT` alarms.
- Filterable alarm table with columns: `Timestamp`, `Severity`, `Component`, `Alarm Code`, `Description`, `Ack Status`.
- Operator acknowledgement workflow dispatching audit log updates.

### 2.5 Historian & Charting View
- Multi-axis time-series plotting powered by high-performance charting libraries (Recharts / ECharts).
- Supports zooming, panning, metric overlays (e.g. SoC vs Temperature vs Discharge Power), and CSV export.

### 2.6 Scenario Runner & Engine Control View
- Controls for central simulation engine: `Play`, `Pause`, `Single Step (+10ms)`, `Reset`, `Speed Slider (0.1x - 100x)`.
- Scenario file picker and progress timeline display.

### 2.7 Plant Configuration View
- Read-only screen that publishes the plant the platform is **actually running**: its identity, its rated power and energy, the topology configuration file it was built from, and the inventory of its equipment.
- Reads `GET /api/v1/topology`, which is served from the application-scoped runtime — the same source the Plant Overview reads — and requires the `READ_CONFIG` permission.
- A value the topology does not declare is published as **absent** and rendered as `NOT SPECIFIED`, never as a placeholder: the equipment models fall back on a placeholder manufacturer, and a placeholder on a configuration screen reads as a configured vendor.
- Every illustrative parameter is labelled as illustrative, per `AGENTS.md` §2.14.
- A platform with no plant attached reports *No plant is attached*; a platform that does not answer reports *The platform did not answer*. Neither case shows a substitute plant.

---

## 3. Communication & Decoupling

- HMI communicates strictly with the FastAPI backend over:
  - **REST API (`/api/v1/...`)**: Scenario loading, authentication, historical query retrieval, setpoint submission.
  - **Platform Session (`/api/v1/auth/login`, `/api/v1/auth/me`)**: Frontend login view validates credentials against the backend auth endpoint, keeps the JWT token exclusively in process memory (`platformSession`), and dispatches the token in `Authorization: Bearer <token>` headers on every request. No `localStorage`, `sessionStorage` or cookies are ever written.
  - **Telemetry polling (`/api/v1/overview`)**: UI views consume the backend plant overview endpoint via the shared `usePlantTelemetry` hook (fixed 2 s polling interval). The backend launcher buffer drives telemetry sampling; no WebSocket endpoint exists, and all rendering happens off the backend source of truth.
- Zero business or physical simulation logic exists in frontend React code.
