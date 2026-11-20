# PowerTwin — Deployment and Cybersecurity Specification

## 1. Container Infrastructure & Docker Compose

PowerTwin is packaged and deployed as a multi-container microservice application managed via `docker-compose.yml`.

```
+-------------------------------------------------------------------------------+
|                           DOCKER COMPOSE TOPOLOGY                             |
|                                                                               |
|  +-------------------+  +-------------------+  +---------------------------+  |
|  |   frontend        |  |    backend        |  |       timescaledb         |  |
|  | Nginx + React HMI |  | FastAPI + Engine  |  | PostgreSQL + TimescaleDB  |  |
|  | Port: 8080        |  | Port: 8000        |  | Port: 5432 (Internal)     |  |
|  +-------------------+  +-------------------+  +---------------------------+  |
+-------------------------------------------------------------------------------+
```

### 1.1 Service Decomposition
- **`backend`**: Python 3.12+ FastAPI app hosting simulation engine, API endpoints, WebSocket gateway, and protocol servers. Runs as non-root user `powertwin`.
- **`frontend`**: Nginx web server serving compiled React/TypeScript static build and proxying API/WS requests to `backend`.
- **`timescaledb`**: TimescaleDB container for time-series metrics and audit persistence.
- **`redis`**: In-memory message broker for high-throughput WebSocket broadcast decoupling.

---

## 2. Network Isolation & Binding Policies

To enforce Safety Rule **SR-003** and **SR-012**:
1. **Internal Container Network**: `timescaledb` and `redis` services bind exclusively to an isolated internal Docker bridge network (`powertwin_internal`) with zero exposed host ports.
2. **Local Interface Binding**: In development and simulation-only modes, the backend binds API and WebSocket listeners strictly to `127.0.0.1` or the container internal gateway.
3. **Hardware Network Separation**: Physical network interfaces connected to field networks (if ever authorized in future phases) must reside on isolated physical NICs completely segregated from the application management network.

---

## 3. Cybersecurity & Access Control

### 3.1 Authentication & Role-Based Access Control (RBAC)
- All REST and WebSocket requests require JWT Bearer tokens or API Keys.
- Three user roles are defined:
  - `Viewer`: Read-only telemetry, SLD, and dashboard view. Cannot submit control setpoints or alter simulation state.
  - `Operator`: Can submit active/reactive setpoints, execute play/pause/step simulation commands, and acknowledge alarms.
  - `Admin`: Full configuration access, scenario loading, plugin management, and audit log inspection.

### 3.2 Audit Trail Cryptographic Integrity
- Audit log records are stored with SHA-256 hash checksums chaining each log entry to the previous entry, preventing undetected record deletion or manipulation.

### 3.3 Container Security Hardening
- Container images built from minimal base images (`python:3.12-slim`, `nginx:alpine`).
- Zero default passwords allowed; all database credentials and secret keys must be passed via secure environment files (`.env`) excluded from version control.
