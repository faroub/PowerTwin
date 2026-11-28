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
2. **Local Interface Binding**: In development and simulation-only modes, the backend binds API and WebSocket listeners strictly to `127.0.0.1` or the container internal gateway. Production deployments bind to `127.0.0.1` or an explicit documented trusted host; `0.0.0.0` (all interfaces) is rejected at startup by the safety invariants.
3. **Hardware Network Separation**: Physical network interfaces connected to field networks (if ever authorized in future phases) must reside on isolated physical NICs completely segregated from the application management network.

---

## 3. Cybersecurity & Access Control

### 3.1 Authentication & Role-Based Access Control (RBAC)
- All REST and WebSocket requests require JWT Bearer tokens or API Keys.
- Three user roles are defined:
  - `Viewer`: Read-only telemetry, SLD, and dashboard view. Cannot submit control setpoints or alter simulation state.
  - `Operator`: Can submit active/reactive setpoints, execute play/pause/step simulation commands, and acknowledge alarms.
  - `Admin`: Full configuration access, scenario loading, plugin management, and audit log inspection.
- Role permissions are enforced server-side by `backend.app.core.authentication`. The frontend role keys match the backend role enum values; UI visibility is a convenience only and never grants authority.
- User accounts and credential hashes are stored in the database via `backend/app/core/users.py`.
- Production accounts are provisioned with `scripts/seed_users.py` (run once after database migration). The script accepts a plain password via `POWERTWIN_DEV_PASSWORD` in development mode only and never embeds credentials in the source or the frontend build.
- In development mode, a process-scoped random password is generated per run. The developer password is not written to any configuration file, to `.env`, or to the frontend build output.
- Authentication is rate-limited and rejects empty, malformed, or expired tokens. Every successful and failed login attempt is appended to the audit trail.

The throttle measures one identity per login attempt: the client identity of
the request (the request peer address by default, or the address the peer
declares in `X-Forwarded-For`/`X-Real-IP` when the peer is declared in the
`TRUSTED_PROXIES` setting) combined with the username the request tries. Every
tracked topic is one username coming from one client identity, so a single user
that repeatedly fails credentials can never exhaust the throttle of every other
user, and a single client can never exhaust the throttle of every account. The
documented capacity of the table is one hundred thousand topics: the least
recently used identities are evicted and every window that carries no active
attempt expires, so the table never grows without limit.

A failed login against a username that exists in no row of the production
database is recorded and throttled the same way as a failed login against a
wrong password, so the rejection message "Incorrect username or password."
never names whether the account exists. The development accounts are only ever
allowed while the platform runs in development or testing mode; the limiter
never tracks them while production is running. The limiter fails with a
`ValueError` at startup instead of silently disabling the throttle when the
`LOGIN_RATE_LIMIT` and `LOGIN_LOCKOUT_SECONDS` configuration is unusable.

### 3.1.1 Session Lifecycle and Logout

A caller makes a session by POSTing to `/api/v1/auth/login`; the response
carries the JWT the frontend stores in memory. Every page thereafter sends that
token as `Authorization: Bearer <token>`, and `get_current_user()` checks its
signature and expiry before any view body runs.

**The access token carries a unique identity.** Every token the platform
issues carries a `jti` claim (a UUIDv4), and that claim is what the platform
names when it has to refuse the token. The identity is created at issue time
and cannot be chosen by the caller.

**Logout revokes the token on the server.** `POST /api/v1/auth/logout` records
the `jti` of the caller's token in the revocation store and answers
`Session terminated and the access token revoked.` From that moment on the
token — and every copy of it, whether it was made before or after the logout —
is refused at every protected route with `401` and `Session token has been
revoked.` The other sessions of the same account are unaffected: they keep
working until they expire or are ended in turn.

The revocation store is chosen by the environment, never by the caller:

| Environment | Store | Lifetime |
| --- | --- | --- |
| `production` | the `revoked_tokens` table (migration `003_revoked_tokens`, ORM `RevokedTokenModel`) | until the token expires |
| `development`, `testing` | the process itself (`InMemoryRevocationStore`) | until the process restarts |

Neither store ever falls back to the other. A store that cannot answer says
so, and the platform **fails closed**: in production a protected route answers
`503 Service Unavailable` — a token it could not check is a token it does not
accept — and a logout that could not record the revocation answers `503` as
well, because the session was not terminated and the platform says so instead
of answering as if it had been. In development the same failure refuses the
request with `401`.

The rows of the table are bounded: a revocation carries the expiry of the token
it names, and the revocations whose token has expired are purged after a
logout.

**The limits the platform states rather than hides:**

- A token issued **before** the platform issued token identities carries no
  `jti`. The platform cannot name it, so it accepts it until it expires and
  says so in the log; a logout of such a token answers `Session terminated;
  the access token cannot be revoked.` Such tokens are gone at the next
  deployment, because every token issued from now on carries an identity.
- **Deactivation of an account does not retroactively revoke its tokens.**
  Deactivation blocks any *new* login for that account; a session that was
  already started runs until it is ended, and its token is then revoked like
  any other. The platform has no user-deactivation operation of its own yet,
  so no revocation is recorded on its behalf.
- Every protected route performs **one indexed lookup** of the `jti` in the
  revocation store. The cost of refusing a revoked token is therefore one
  primary-key read per request in production.
- The frontend ends the browser session first and asks the platform to revoke
  the token afterwards. When the platform cannot be reached, the browser
  session still ends and the HMI says that the token could not be revoked and
  stays valid until it expires.

### 3.2 Audit Trail Cryptographic Integrity

Every command, setpoint change, configuration change, fault and operator
action is recorded in one dedicated, append-only, tamper-evident journal
(`backend/app/core/operator_journal.py`). The journal is a JSON Lines file
that is only ever opened in append mode, and every entry carries the SHA-256
hash of its predecessor and of its own canonical content. Changing, removing,
reordering or truncating an entry breaks the chain from that point on, and
`OperatorActionJournal.verify()` reports the first break — so record deletion
or manipulation cannot go undetected.

The chain continues across a restart, the journal is process-scoped so that
two applications in one process cannot write two trails that both claim to be
complete, and it is always on: `AGENTS.md` §2.10 requires the record, so
there is deliberately no setting that turns it off. `OPERATOR_JOURNAL_PATH`
and `OPERATOR_JOURNAL_FSYNC` are the only knobs, and `fsync` defaults to on.

In the Compose deployments the journal lives on the named `operator_journal`
volume at `/app/var/operator_actions.jsonl`, so the trail survives a container
replacement: a trail that disappears with the container that wrote it cannot
answer a warranty or dispute question. Copy the file off the host if the
trail has to survive the loss of the disk.

The boundary worth knowing about is that a journal write that **fails** is
fail-open: the error is logged as an error, the journal marks itself
`degraded` and exposes the message, but the action is not rolled back and the
entry is not written later, so the trail has a gap. A simulation action cannot
be undone, and failing closed would make the plant uncontrollable the moment
the disk fills. This is recorded in `docs/POWER_TWIN_KNOWN_LIMITATIONS.md`
§4.9.

### 3.3 Container Security Hardening
- Container images built from minimal base images (`python:3.12-slim`, `nginx:alpine`).
- Zero default passwords allowed; all database credentials and secret keys must be passed via secure environment files (`.env`) excluded from version control.
- `deployment/docker-compose.yml` and the root `docker-compose.yml` publish every port bound to a loopback address (`127.0.0.1`) unless explicit published networking is required. No service is exposed to arbitrary networks by default.
- Web application firewall, secret scanning, and dependency vulnerability checks run on every CI push and on a scheduled nightly cycle.

### 3.4 Secrets & Credential Hygiene

The following rules are enforced by the code and covered by
`tests/test_config_secrets_hygiene.py` and `tests/test_deployment_binding.py`.

**No credential is ever written to an audit trail.**
`backend/app/core/secrets.py` provides the single redaction implementation used by
every audit path. A value is redacted when its *parameter name* matches a known
sensitive fragment (password, secret, token, credential, api key, private key,
passphrase, authorization, salt, signature) or when a free-form string embeds
credentials in a URL userinfo section (`scheme://user:password@host`). The
placeholder `***REDACTED***` carries no information about the original value.

| Audit path | Redaction applied |
| --- | --- |
| `AuditLog.record` / `AuditLog.record_failure` | `details` payload walked recursively; sensitive keys replaced, URL credentials rewritten |
| `ConfigChangeAuditLog.log_change` | `old_value` / `new_value` replaced when `parameter_name` is sensitive; otherwise URL credentials in the value are rewritten |

**A blank secret is never treated as a configured secret.**
`Settings` applies field validators to `POSTGRES_PASSWORD` and `JWT_SECRET_KEY`.
A variable that is exported but empty (or whitespace only) is replaced by a
cryptographically random per-process value, so a Compose file that expands an
undefined variable to an empty string can never authenticate with no password.
In production the blank `JWT_SECRET_KEY` is preserved deliberately so that
`validate_safety_invariants()` fails the start-up closed.

**Connection strings are logged redacted.**
`Settings.REDACTED_DATABASE_URL` returns the database URL with its password
replaced by the placeholder. Any log line, error message or API response that
mentions the database URL must use this property; `Settings.DATABASE_URL` must
never leave the process.

**Deployment fails fast on a missing secret.**
Both Compose files reference the database password with the Compose fail-fast
form `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set - ...}`. An unset or
empty variable aborts `docker compose config` and `docker compose up` with a
non-zero exit status instead of starting the historian with an empty password.

**Templates carry placeholders only.**
`.env.example` and `configs/.env.example` list every supported setting and leave
every credential *empty* — a placeholder such as `<your-secure-password>` would
become a publicly known credential the moment the template is copied verbatim.
Both templates bind the API server and the protocol gateway to `127.0.0.1`, and
`ALLOW_EXTERNAL_MODBUS_WRITES=False` is present in both, so the external
controller write path is never enabled by copying a template.

**Known limitations.**

- The redaction rules are name-based and pattern-based. A secret stored under a
  name that carries no sensitive fragment (for example `POSTGRES_USER` used as
  a password) is not redacted. The rule set is deliberately conservative and
  errs towards redacting.
- The JWT signing key is generated per process in development. Tokens therefore
  do not survive a backend restart; this is intentional and must not be changed
  for production deployments, which must set an explicit `JWT_SECRET_KEY`.
