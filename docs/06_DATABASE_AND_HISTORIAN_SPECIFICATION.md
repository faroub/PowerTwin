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

---

## 5. Implemented Ingestion & Durability Policy

> **STATUS: IMPLEMENTED.** The subsections below describe the running implementation in
> `backend/app/historian/service.py`. Sections 2 and 3 above remain the target design;
> see `docs/POWER_TWIN_KNOWN_LIMITATIONS.md` for the schema drift between the target
> design and the implemented SQLAlchemy models.

### 5.1 Three-Stage Ingestion Path

1. **In-memory ring buffer** — the simulation tick loop pushes telemetry, command, and
   alarm records into three thread-safe `queue.Queue` buffers (default capacity 10,000
   entries each). `put_nowait` is used so a slow database can never block the tick loop.
2. **Database flush** — `HistorianService.flush_buffer_to_db()` drains the queues and
   commits the rows in a single transaction. On commit failure the transaction is rolled
   back and **every drained record is re-persisted to the disk overflow** before the
   method returns `(0, 0, 0)`.
3. **Disk overflow** — when a buffer is 100% full, the incoming record is appended to an
   append-only JSON Lines file under `backend/app/historian/overflow/`. A `fsync` is
   issued after every append so a process crash cannot lose an overflowed record.

### 5.2 Overflow File Rotation

An overflow file is rotated to a timestamped archive (`<stem>.<epoch_us>.json`) once it
exceeds `OVERFLOW_MAX_BYTES` (64 MiB). Rotation bounds the disk footprint of a
long outage; archives are replayed in chronological order, so rotation never discards
a record.

### 5.3 Overflow Replay

`HistorianService.replay_overflow_to_db()` reads every live and rotated overflow file,
inserts the records into the database, and commits.

- The overflow files are truncated **only after a successful commit**. A failed commit
  rolls back and leaves every record on disk.
- Corrupt trailing lines (for example a partially written record after a crash) are
  skipped individually; one bad line never aborts the replay of the rest.
- `HistorianService.flush_all_to_db()` performs the memory flush first and then the
  disk replay. A record is therefore never written twice and never lost.

### 5.4 Observability

`HistorianService.get_buffer_status()` reports the memory buffer occupancy.
`HistorianService.get_overflow_status()` reports the pending disk-overflow record
count, file count, and byte size per stream.

### 5.5 Documented Limitations

- Overflow files are local to a single backend process. A multi-replica deployment
  requires a shared volume or an external queue; this is **NOT IMPLEMENTED**.
- The historian does not currently downsample on ingest. The `sampling_step_ns`
  down-sampling is applied at query time only.

### 5.6 Migration Policy

The history tables are created by the Alembic migrations of `backend/migrations/`.
A release ships the migration that produces the schema the historian expects, and
the deployment applies that migration before any backend worker starts: the
`migrate` service of `docker-compose.yml` runs `alembic upgrade head` once,
waits for `timescaledb` to be `service_healthy` and exits 0 when the last
migration is applied.

The application never migrates the database. A worker applies no migration and
the deployment runs the migration exactly once, so a database that never ran
the migration of the release reports `schema_missing` from
`/health/readiness` rather than a generic connection failure. The migration is
an explicit operator action, started with `docker compose up -d migrate`, and
the same command is the one the release job runs against an ephemeral
TimescaleDB.

---

## 6. Implemented Historian Query API

> **STATUS: IMPLEMENTED.** `backend/app/api/v1/historian.py`, backed by
> `backend/app/historian/query.py` (`HistorianQueryEngine`).

All endpoints are read-only and require the `READ_TELEMETRY` permission, so an
`OBSERVER` account can browse history without gaining any control capability.

| Method | Path | Purpose | Max rows |
| --- | --- | --- | --- |
| `GET` | `/api/v1/historian/telemetry` | Time-series retrieval with equipment/tag/run filters, time range, and query-time downsampling | 10,000 |
| `GET` | `/api/v1/historian/commands` | Traceable command audit log | 5,000 |
| `GET` | `/api/v1/historian/alarms` | Alarms and events log | 5,000 |
| `GET` | `/api/v1/historian/warranty/{container_id}` | Battery warranty and degradation metrics | 1 |

### 6.1 Validation Rules

- `start_time_ns` must be less than or equal to `end_time_ns`; otherwise the endpoint
  returns HTTP 422.
- `limit` is bounded per endpoint by a `Query(ge=1, le=<max>)` constraint, so an
  unbounded time-series scan can never be requested.
- Unauthenticated requests return HTTP 401; a role without `READ_TELEMETRY` returns
  HTTP 403.
- An unknown `container_id` returns HTTP 404 rather than an empty payload.
