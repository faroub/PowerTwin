# PowerTwin — Software Architecture Specification

## 1. High-Level Architecture Overview

PowerTwin follows a modular, decoupled, event-and-tick-driven software architecture designed around clean domain separation, strict physical unit standards, deterministic execution, and safe system boundaries.

```mermaid
graph TD
    subgraph Frontend Layer
        HMI["React + TypeScript HMI"]
        SLD["Single-Line Diagram (SLD)"]
        Charts["Historian & Charting"]
    end

    subgraph API & Gateway Layer
        FastAPI["FastAPI REST & WebSocket Gateway"]
        Auth["RBAC & Security Guardrails"]
    end

    subgraph Core Engine Layer
        Clock["Deterministic Clock & Scheduler"]
        DAG["Execution DAG Engine"]
        State["Simulation State Store"]
    end

    subgraph Domain Models Layer
        Battery["Battery Physics Models (Cell/Rack/Container)"]
        PCS["PCS & Inverter Models"]
        BoP["BoP / Transformer / Switchgear Models"]
        Grid["Grid & POI Models"]
    end

    subgraph Control Systems Layer
        BMS["BMS Controller Models"]
        PPC["Power Plant Controller (PPC)"]
        EMS["Energy Management System (EMS)"]
    end

    subgraph External & Plugin Layer
        Plugins["Vendor Plugin Manager"]
        ProtoEmu["Protocol Emulators (Modbus / DNP3)"]
    end

    subgraph Persistence Layer
        DB["PostgreSQL + TimescaleDB"]
        Audit["Audit Logger"]
    end

    HMI --> FastAPI
    SLD --> FastAPI
    Charts --> FastAPI
    FastAPI --> Auth
    Auth --> Clock
    Clock --> DAG
    DAG --> State
    State --> Battery
    State --> PCS
    State --> BoP
    State --> Grid
    DAG --> BMS
    DAG --> PPC
    DAG --> EMS
    DAG --> Plugins
    ProtoEmu <--> State
    State --> DB
    Auth --> Audit
```

---

## 2. Component Decomposition

### 2.1 Core Simulation Engine (`backend/engine/`)
- **Responsibility**: Manages the simulation lifecycle, deterministic clock ticks, model execution DAG, state serialization, pause/step/resume commands, and scenario replay.
- **Independence**: Has zero knowledge of HMI components, database drivers, or specific protocol schemas. Communicates via in-memory typed state records.

### 2.2 Equipment Physical Models (`backend/models/`)
- **Responsibility**: Calculates physical state changes per tick using mathematical and electro-thermal equations.
- **Submodules**:
  - `battery/`: Equivalent circuit models (ECM), electrochemical thermal dynamics, SoC/SoH estimation.
  - `pcs/`: Inverter conversion efficiency, AC/DC power coupling, reactive power limits.
  - `bop/`: Transformer impedance, MV/HV switchgear breaker dynamics, HVAC thermal extraction.
  - `grid/`: POI voltage source, grid frequency dynamics, synthetic fault injection.

### 2.3 Control System Stack (`backend/controllers/`)
- **Responsibility**: Implements BESS operational logic across the control hierarchy.
- **Submodules**:
  - `bms/`: Rack and master BMS state machines, voltage/temperature protection limiters, balancing logic.
  - `ppc/`: Active power regulation, Volt-VAR control, ramp rate limiters, grid code compliance functions.
  - `ems/`: High-level economic and operational dispatch engines (peak shaving, arbitrage, frequency response).

### 2.4 Protocol Emulators (`backend/protocols/`)
- **Responsibility**: Translates internal simulation state to industrial communication protocols (Modbus TCP, DNP3, SunSpec) for CIL testing.
- **Boundary Rule**: Disabled by default. Writable registers map to validated command interfaces only.

### 2.5 API Gateway (`backend/api/`)
- **Responsibility**: Exposes secure REST endpoints for scenario management, configuration loading, and control commands; streams telemetry to the HMI via WebSockets.

### 2.6 Persistence & Historian (`backend/db/`)
- **Responsibility**: Stores plant configurations, scenario definitions, audit trails, and high-frequency time-series telemetry using TimescaleDB.

### 2.7 Frontend Web HMI (`frontend/`)
- **Responsibility**: Provides operators with real-time visualization, single-line diagrams (SLD), interactive controls, alarm banners, and historical trends. Built with React and TypeScript.

### 2.8 Plugin System (`plugins/`)
- **Responsibility**: Provides sandboxed interfaces for third-party or vendor-specific equipment models and control strategies.

---

## 3. Core Architectural Invariants

### 3.1 Strict Physical Unit Standard (SI Units)
All internal variable definitions, interface payloads, and calculations **MUST** use explicit SI units:
- Voltage: Volts ($V$)
- Current: Amperes ($A$)
- Power (Active): Watts ($W$)
- Power (Reactive): Volt-Amperes Reactive ($VAR$)
- Energy: Joules ($J$) or Watt-hours ($Wh$)
- Temperature: Degrees Celsius ($^\circ C$) or Kelvin ($K$)
- Resistance: Ohms ($\Omega$)
- Capacitance: Farads ($F$)
- Frequency: Hertz ($Hz$)
- Time: Seconds ($s$) or Integer Ticks ($\mu s$)

### 3.2 State Value Qualification & Explicit Value Types
Every signals and interface object must cleanly distinguish between four distinct values:
1. **Requested Setpoint**: Desired target from operator/EMS.
2. **Accepted Command**: Validated target accepted by PPC/BMS after applying safety limits.
3. **Actual Output**: Physical state generated by PCS/battery dynamics.
4. **Measured Value**: Telemetry value reported by simulated sensors (including noise/accuracy tolerances).

Each measurement payload must adhere to the standard envelope:
```python
class Measurement(BaseModel):
    value: float
    unit: str
    timestamp_ns: int
    quality: QualityFlag  # GOOD, BAD, UNCERTAIN
    source_id: str
```

### 3.3 Configuration-Driven Plant Topology
Plant layouts, equipment counts, container groupings, and transformer specifications are defined entirely via declarative YAML/JSON configuration files validated against Pydantic schemas. Zero plant topologies are hardcoded into model source code.
