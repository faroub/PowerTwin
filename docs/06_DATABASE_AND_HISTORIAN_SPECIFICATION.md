# PowerTwin — Database and Historian Specification

## 1. Overview

PowerTwin utilizes **PostgreSQL** paired with the **TimescaleDB** extension for high-performance time-series telemetry storage, audit logging, configuration management, and analytical query execution.

---

## 2. Database Schema Architecture

### 2.1 Telemetry Hypertable (`telemetry_data`)
Stores high-frequency sensor and state measurements recorded during simulation execution.

```sql
CREATE TABLE telemetry_data (
    timestamp_ns BIGINT NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    val_float DOUBLE PRECISION,
    quality_flag VARCHAR(16) NOT NULL DEFAULT 'GOOD',
    simulation_run_id UUID NOT NULL,
    PRIMARY KEY (timestamp_ns, entity_id, metric_name, simulation_run_id)
);

SELECT create_hypertable('telemetry_data', 'timestamp_ns', chunk_time_interval => 86400000000000);
```

### 2.2 Audit Log Table (`audit_log`)
Stores an immutable log of all operator setpoint commands, configuration edits, mode changes, and security events.

```sql
CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp_wall TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    simulation_tick_ns BIGINT NOT NULL,
    operator_id VARCHAR(64) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    target_entity VARCHAR(64) NOT NULL,
    previous_value JSONB,
    new_value JSONB,
    status VARCHAR(16) NOT NULL,
    hash_checksum VARCHAR(64) NOT NULL
);
```

### 2.3 Events and Alarms Table (`events_and_alarms`)
Stores raised faults, warnings, and protection events across simulation runs.

```sql
CREATE TABLE events_and_alarms (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_run_id UUID NOT NULL,
    timestamp_ns BIGINT NOT NULL,
    source_component VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL, -- INFO, WARNING, FAULT, CRITICAL
    alarm_code VARCHAR(32) NOT NULL,
    description TEXT NOT NULL,
    acknowledged BOOLEAN DEFAULT FALSE,
    cleared_timestamp_ns BIGINT
);
```

---

## 3. Data Retention & Continuous Aggregations

### 3.1 Compression Policy
- Telemetry chunks older than 7 days are automatically compressed using TimescaleDB column-oriented compression sorted by `entity_id, timestamp_ns`.

### 3.2 Continuous Aggregates (Rollups)
- **1-Minute Summary**: Materialized view calculating `min`, `max`, `avg` values per metric per minute for fast long-term dashboard charting.
- **1-Hour Summary**: Materialized view for long-term multi-month degradation and energy throughput reporting.

---

## 4. Query Performance Requirements
- Telemetry ingestion throughput: $\ge 100,000\text{ metric writes/second}$.
- Dashboard charting query response: $< 100\text{ ms}$ for 24-hour time range query using continuous aggregates.
