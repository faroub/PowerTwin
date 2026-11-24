# PowerTwin — Communication Specification

## 1. Overview

PowerTwin provides an **isolated** protocol gateway that lets an external PPC,
EMS or SCADA controller drive a *simulated* BESS plant over Modbus TCP.

The gateway is a **server only**. It never initiates an outbound connection,
never scans a network and never addresses physical equipment. Every write that
reaches the simulation passes a command validation boundary first, and every
accepted or rejected write is written to an auditable log.

**Status of the protocol emulators described in this document:**

| Emulator | Status | Notes |
| :--- | :--- | :--- |
| Modbus TCP server (holding registers) | **IMPLEMENTED** | Real TCP socket, `pymodbus` 3.9.2, loopback only. |
| Modbus TCP input registers (FC04) | **NOT IMPLEMENTED** | Returns a Modbus `ILLEGAL_FUNCTION` exception. |
| Modbus RTU | **NOT IMPLEMENTED** | No serial transport exists. |
| DNP3 outstation (IEEE 1815) | **NOT IMPLEMENTED** | No code exists; the earlier draft of this document described it aspirationally. |
| SunSpec Modbus | **NOT IMPLEMENTED** | No code exists; the earlier draft of this document described it aspirationally. |

Anything not marked *IMPLEMENTED* in this table is **NOT IMPLEMENTED** and must
not be presented as available to an integrator.

---

## 2. Architecture

```
+-------------------------------------------------------------------------------+
|                       EXTERNAL CONTROLLER / SCADA                             |
|                    (Modbus TCP master, loopback only)                         |
+-------------------------------------------------------------------------------+
       |  FC03 read holding / FC06, FC16 write holding
       v
+-------------------------------------------------------------------------------+
|                      POWERTWIN PROTOCOL EMULATION LAYER                       |
|  backend/app/communication/modbus_server.py   listener, register table        |
|  backend/app/communication/modbus_datastore.py codec, datastore context       |
|  backend/app/communication/gateway_service.py validation, audit, watchdog    |
|  backend/app/communication/adapter.py         register map specification      |
+-------------------------------------------------------------------------------+
       |  validated setpoint, under plant.simulation_engine.execution_lock
       v
+-------------------------------------------------------------------------------+
|                         CENTRAL SIMULATION ENGINE                             |
|       Equipment Controller -> PPC -> EMS -> PCS -> Battery -> BoP/POI         |
+-------------------------------------------------------------------------------+
```

The three layers are kept strictly separate:

* **modbus_server.py** owns the socket and the register table. It knows nothing
  about the plant.
* **modbus_datastore.py** owns the wire codec and the pymodbus datastore
  context. It knows nothing about the plant.
* **gateway_service.py** owns the semantic validation, the audit trail, the
  routing into the plant and the watchdog. It opens no socket itself.

The simulation engine remains independent of the protocol implementation: it
can be run with the gateway completely disabled.

---

## 3. Modbus TCP server

### 3.1 Listener

| Property | Value |
| :--- | :--- |
| Transport | TCP, `pymodbus` 3.9.2 (`ModbusTcpServer`) |
| Bind address | Loopback only (`127.0.0.1`, `localhost`, `::1`) |
| Default port | `5020` (`PROTOCOL_GATEWAY_PORT`) |
| Default state | **Disabled** — no socket is opened |
| Unit ID | 1 (the pymodbus slave context is `single=True`) |

The listener refuses to start for any address that is not a loopback address.
This check is performed before the socket is created, so the gateway cannot be
pointed at real equipment by a configuration mistake.

The listener runs on its own event loop in a dedicated daemon thread. Every
mutation of the plant that is caused by an external write is performed while
holding `plant.simulation_engine.execution_lock`, so a command can never be
applied in the middle of a simulation tick.

### 3.2 Supported function codes

| FC | Name | Status |
| :--- | :--- | :--- |
| 3 | Read Holding Registers | **IMPLEMENTED** |
| 6 | Write Single Register | **IMPLEMENTED** (register-count rules still apply) |
| 16 | Write Multiple Registers | **IMPLEMENTED** |
| 43 / 0x2B | Read Device Identification | **IMPLEMENTED** — reports the simulator identity |
| 4 | Read Input Registers | **NOT IMPLEMENTED** — `ILLEGAL_FUNCTION` |
| 1, 2, 5, 15, 22, 23 | Coils / discrete inputs / other | **NOT IMPLEMENTED** — `ILLEGAL_FUNCTION` |

### 3.3 Device identification

Function code 43 (read device identification) reports the identity of the
**simulator**, never of real equipment:

| Object id | Name | Value |
| :--- | :--- | :--- |
| 0x00 | VendorName | `PowerTwin` |
| 0x01 | ProductCode | `PowerTwin BESS CIL Gateway` |
| 0x02 | MajorMinorRevision | `1.0.0` |
| 0x03 | VendorUrl | `https://localhost` |
| 0x04 | ProductName | `PowerTwin Modbus TCP CIL Gateway` |
| 0x05 | ModelName | `PowerTwin-CIL` |
| 0x06 | UserApplicationName | `PowerTwin BESS Simulator (simulation only)` |

Read code `0x01` (basic) returns objects 0x00–0x02; read code `0x02`
(regular) and `0x03` (full) return every object.

### 3.4 Configuration

| Setting | Environment variable | Default | Meaning |
| :--- | :--- | :--- | :--- |
| Listener enabled | `PROTOCOL_GATEWAY_ENABLED` | `False` | When false, no socket is opened at all. |
| Bind host | `PROTOCOL_GATEWAY_HOST` | `127.0.0.1` | Must be a loopback address. |
| Bind port | `PROTOCOL_GATEWAY_PORT` | `5020` | TCP port of the listener. |
| External writes | `ALLOW_EXTERNAL_MODBUS_WRITES` | `False` | When false, every write is rejected with `SLAVE_FAILURE`. |
| Watchdog timeout | `watchdog_timeout_ns` on the service | `5 s` | Stale-heartbeat timeout. |

`configs/cil_external_ppc_config.yaml` mirrors these settings and carries the
same register map as the implementation; the map is verified against
`DEFAULT_REGISTER_MAP` in the code.

---

## 4. Register map

Only **holding registers** are exposed. A 32-bit value occupies two consecutive
registers, a 16-bit value occupies one register.

### 4.1 Telemetry (read-only)

| Address | Name | Type | Unit | Description |
| :--- | :--- | :--- | :--- | :--- |
| 0 | `PLANT_ACTIVE_POWER_MW` | FLOAT32 | MW | Plant net active power export (+MW) |
| 2 | `PLANT_REACTIVE_POWER_MVAR` | FLOAT32 | MVAR | Plant net reactive power (+MVAR) |
| 4 | `POI_VOLTAGE_KV` | FLOAT32 | kV | POI AC nominal voltage |
| 6 | `GRID_FREQUENCY_HZ` | FLOAT32 | Hz | Grid operating frequency |
| 8 | `AVERAGE_SOC_PCT` | FLOAT32 | pct | Plant average state of charge |
| 10 | `EQUIPMENT_AVAILABILITY_PCT` | FLOAT32 | pct | Plant equipment availability |
| 12 | `ACTIVE_ALARMS_COUNT` | UINT32 | count | Total active critical alarm count |

A write to any of these addresses is rejected with `ILLEGAL_ADDRESS`; it is
never silently accepted.

Telemetry is refreshed from the plant by
`ProtocolGatewayService.sync_telemetry_from_plant()`. A non-finite measurement
(NaN, infinity) is rejected and the register keeps its previous value, because
a NaN in a telemetry register would be read by the controller as a valid plant
measurement.

### 4.2 Commands (read-write)

| Address | Name | Type | Unit | Range | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 100 | `COMMAND_ACTIVE_POWER_W` | FLOAT32 | W | ±50 000 000 | Active power setpoint (+W discharge, −W charge) |
| 102 | `COMMAND_REACTIVE_POWER_VAR` | FLOAT32 | VAR | ±50 000 000 | Reactive power setpoint (+VAR supply, −VAR absorb) |
| 104 | `WATCHDOG_HEARTBEAT_COUNTER` | UINT32 | count | 0 … 4 294 967 295 | External controller heartbeat counter |
| 106 | `COMMAND_EMS_MODE` | UINT16 | enum | 0 … 3 | EMS operational mode |
| 108 | `COMMAND_RESET_FAULTS` | UINT16 | flag | 0 … 1 | Reset active equipment faults (1 = reset) |

`COMMAND_EMS_MODE` encoding: `0 = MANUAL_DISPATCH`, `1 = SCHEDULED_PROFILE`,
`2 = PEAK_SHAVING`, `3 = FREQUENCY_RESPONSE`.

**Sign convention:** positive active power is discharge/export, negative is
charge/import. The same convention is used throughout the platform.

### 4.3 Wire encoding

Values are encoded big-endian, **high word first**, in IEEE 754 format for the
float types:

```
FLOAT32 at address 100:   register 100 = high word, register 101 = low word

  0x42C8_0000  ->  100.0  ->  register 100 = 0x42C8, register 101 = 0x0000
```

Reference helpers (Python):

```python
import struct
def encode_float32(value: float) -> list[int]:
    high, low = struct.unpack(">HH", struct.pack(">f", value))
    return [high, low]

def decode_float32(registers: list[int]) -> float:
    return float(struct.unpack(">f", struct.pack(">HH", *registers))[0])
```

A read that starts or ends outside the documented map is rejected with
`ILLEGAL_ADDRESS`; a read never returns partially mapped data.

---

## 5. Exception codes

| Rejection reason | Modbus exception | Code |
| :--- | :--- | :--- |
| `REJECTED_READ_ONLY` | `ILLEGAL_ADDRESS` | 2 |
| `REJECTED_INVALID_ADDRESS` | `ILLEGAL_ADDRESS` | 2 |
| `REJECTED_INVALID_DATA_TYPE` | `ILLEGAL_VALUE` | 3 |
| `REJECTED_OUT_OF_RANGE` | `ILLEGAL_VALUE` | 3 |
| `REJECTED_NON_FINITE` | `ILLEGAL_VALUE` | 3 |
| `REJECTED_WRITES_DISABLED` | `SLAVE_FAILURE` | 4 |
| `REJECTED_COMMUNICATION_LOSS` | `SLAVE_FAILURE` | 4 |
| `REJECTED_STALE_HEARTBEAT` | `SLAVE_FAILURE` | 4 |
| Unsupported function code | `ILLEGAL_FUNCTION` | 1 |

"Register count does not match the declared data type" is an
`ILLEGAL_VALUE`: a 32-bit register written with a single register is a
malformed value, not a bad address.

---

## 6. Command validation & ingress safety boundary

Every write that arrives on the wire passes the following ordered checks. A
command that fails any check is rejected, audited, and **never** reaches the
plant.

```
+-------------------------------------------------------------------------------+
|                       COMMAND VALIDATION BOUNDARY                             |
|                                                                               |
|  1. Address check   : The address must be a documented register start.        |
|  2. Shape check     : The register count must match the declared data type.   |
|  3. Decoding        : The payload must decode into the declared data type.    |
|  4. Write enable    : ALLOW_EXTERNAL_MODBUS_WRITES must be true.              |
|  5. Access          : A telemetry register may not be written.                |
|  6. Range           : The value must lie inside the documented range.          |
|  7. Finiteness      : NaN and infinity are rejected.                          |
|  8. Heartbeat order : A heartbeat counter must strictly advance.              |
|  9. Line state      : A simulated communication loss refuses every command.   |
| 10. Routing         : The setpoint is applied under the execution lock.       |
+-------------------------------------------------------------------------------+
```

Checks 1–3 happen in the datastore, before the value is interpreted as a
command. Checks 4–9 happen in the gateway service. Check 10 is the actual
dispatch into the plant.

**Ramp-rate limiting** is applied by the PPC layer of the simulation
(`plant.ppc`), not by the protocol layer: the protocol layer delivers the
*requested* setpoint, and the PPC decides what the plant actually accepts.
The audit trail records both.

---

## 7. Watchdog and the defined safe state

Register 104 carries a monotonically increasing heartbeat counter.

* A heartbeat that does **not** advance past the last accepted counter is a
  protocol violation. It is rejected with `SLAVE_FAILURE` and audited as
  `REJECTED_STALE_HEARTBEAT`. It does **not** refresh the watchdog.
* When the last accepted heartbeat is older than the watchdog timeout, the
  gateway places the simulated plant in the **defined safe state**:
  * the active and reactive power dispatch is driven to zero,
  * the equipment controller performs a graceful shutdown into `STANDBY`.
* The safe state is applied **once per timeout episode** and is audited as
  `WATCHDOG_SAFE_STATE`.

The safe state is deliberately **not** an emergency stop. An emergency trip is
a certified hardware protection function; a software watchdog must never
produce one. The transition is a *graceful* shutdown, and the audit trail
records it as such.

---

## 8. Audit trail

Every write attempt — accepted or rejected — produces an entry in the
`ControlCommandLog`, with:

* the simulation timestamp (`timestamp_ns`),
* the source (`EXTERNAL_CIL:<client id>`), where the client id includes the
  peer address of the Modbus master,
* the target component,
* the requested value and the accepted value,
* the status (`ACCEPTED`, `REJECTED_INTERLOCK`, …),
* the reason.

Rejections that cannot be decoded (bad address, wrong register count) are
audited as well, so that no attempt is invisible.

---

## 9. Safety guardrails

* **Default server state**: the listener is disabled and bound to `127.0.0.1`.
  No socket is opened until `PROTOCOL_GATEWAY_ENABLED` is explicitly set.
* **Hardware prohibition**: the gateway acts exclusively as a server. It never
  initiates a client connection, performs an ARP discovery or transmits a
  packet onto a physical local network.
* **No silent fallback**: the gateway never falls back from a real connection
  to a simulated device, or the other way round. There is only one device
  model, and it is simulated.
* **Loopback enforcement**: a non-loopback bind address is refused with an
  error and the listener does not start.
* **Write enablement is separate from listener enablement**: opening the
  listener and allowing writes are two independent, deliberate operator
  actions.
* **Audit logging**: see section 8.

---

## 10. Known limitations

* **Single slave unit.** The server registers a single unit id (1). Unit id
  routing for multiple slaves is **NOT IMPLEMENTED**.
* **Holding registers only.** Input registers, coils and discrete inputs are
  **NOT IMPLEMENTED**.
* **No SunSpec or DNP3.** See the status table in section 1.
* **The watchdog is polled.** The safe state is applied when
  `check_watchdog_heartbeat()` is called by the host application. It is not
  driven by a timer inside the gateway, so a host that never polls it never
  trips it.
* **No TLS.** The listener is plain Modbus TCP on loopback. It relies on the
  loopback boundary for isolation rather than on transport security.
* **No authentication.** Modbus TCP has no authentication mechanism. The
  loopback binding is the only access control.
* **The register map is fixed in code.** `DEFAULT_REGISTER_MAP` is the
  authoritative map; the YAML file mirrors it but is not loaded at runtime.
* **Single-process only.** The listener runs in a thread of the application
  process. It is not a standalone daemon and is not horizontally scalable.
* **Python 3.14 asyncio internals.** The shutdown sequence removes the accept
  callback with the private `loop._stop_serving()` helper and uses the raw
  sockets of the `asyncio.Server`, because `asyncio.Server.sockets` returns
  read-only wrappers without a `close()` method. Both are guarded: if a future
  interpreter removes them, the gateway degrades to a single-step shutdown
  instead of failing.
