# PowerTwin — Deployment Hardening and Operational Readiness Specification (WP13)

## 1. Overview & Deployment Profiles

PowerTwin provides three deployment profile configuration templates:

1. **Developer Workstation** ([deployment/profiles/developer_workstation.yaml](file:///home/faroub/Documents/Projects/PowerTwin/deployment/profiles/developer_workstation.yaml)): Fast feedback, local development.
2. **Industrial On-Premises Server** ([deployment/profiles/industrial_server.yaml](file:///home/faroub/Documents/Projects/PowerTwin/deployment/profiles/industrial_server.yaml)): Hardened production server deployment. Hardware integration remains **strictly disabled**.
3. **Isolated CIL Test Environment** ([deployment/profiles/cil_test_environment.yaml](file:///home/faroub/Documents/Projects/PowerTwin/deployment/profiles/cil_test_environment.yaml)): Laboratory test rig bound strictly to loopback (`127.0.0.1:5020`).

---

## 2. Required Ports & Network Boundaries

| Port | Protocol | Boundary | Purpose |
| :--- | :--- | :--- | :--- |
| `8000` | HTTP / WebSocket | Internal / DMZ | FastAPI REST API & Telemetry Streaming |
| `5173` / `80` | HTTP | DMZ | Industrial React Web HMI |
| `5432` | PostgreSQL | Private DB Subnet | TimescaleDB Historian Storage |
| `5020` | Modbus TCP | Isolated Loopback (`127.0.0.1`) | CIL Protocol Gateway |

---

## 3. Container Security Settings

All production containers run under hardened security contexts:
- **Non-Root User**: Runs as `powertwin` (`UID: 1000`, `GID: 1000`).
- **Read-Only Root Filesystem**: Root filesystem is read-only (`read_only: true`).
- **Dropped Capabilities**: All Linux capabilities dropped (`cap_drop: ["ALL"]`).
- **No New Privileges**: Set `no-new-privileges: true`.

---

## 4. Database Backup & Restore Policy

### Backup Command (TimescaleDB / PostgreSQL)
```bash
pg_dump -h localhost -U powertwin -F c -b -v -f powertwin_backup_$(date +%Y%m%d_%H%M%S).dump powertwin_db
```

### Restore Command
```bash
pg_restore -h localhost -U powertwin -d powertwin_db -v powertwin_backup_20250101_000000.dump
```

---

## 5. Database Migration Policy

The database of a deployment holds the schema of the release that shaped it.
`Migrate` is an explicit operator action, not a startup step: the
`migrate` service of the deployment runs it once, waits for `timescaledb` to be
`service_healthy` and exits when the last migration is applied. The backend
never starts a migration, so no worker applies the schema and every worker does
not repeat it.

The migration reads the same credentials as the service it precedes, so the
deployment of the database and the deployment of the application stay one
change. A release that is deployed without the migration of that release reads
a readiness failure, not a database:

```bash
docker compose up -d --build
```

A database that is older than the release of the migration is repaired when the
migration is run again:

```bash
docker compose up -d migrate
```

The deployment of the readiness probe at `/health/readiness` answers one of
three reasons:

- `unconfigured` — the application resolved no database URL.
- `unreachable` — the database answers the URL but not the connection.
- `schema_missing` — the database is reachable and has a schema that the
  migrations of the release have not applied, so the probe names the tables
  that are missing.

A readiness answer of `schema_missing` tells the operator to run the migration
and nothing else.

---

## 6. Non-Certification & Safety Disclaimer

> [!CAUTION]
> **DISCLAIMER OF LIVE CONTROL SUITABILITY**:
> PowerTwin is a software simulation and emulation platform operating strictly in **SIMULATION ONLY** mode (`SIMULATION_ONLY = True`, `HARDWARE_INTEGRATION_ENABLED = False`).
> 
> PowerTwin is **NOT certified or suitable for direct control of live battery hardware or utility-scale high-voltage electrical assets**. Direct connection to physical battery contactors or real inverter Modbus channels is strictly prohibited.
