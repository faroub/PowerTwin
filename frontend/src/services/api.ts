/**
 * Frontend API client for the PowerTwin BESS platform.
 *
 * All read/write calls target the local FastAPI backend through the Vite dev proxy
 * (`/api/v1/...`) or, at build time, the reverse proxy exposing `/api/v1/...` on the
 * same origin. Every request that touches platform state carries the platform session
 * token.
 *
 * NOTE: The token lives exclusively in process memory (in-memory React state), i.e. it is
 * never stored on the client filesystem. This keeps the platform in the default
 * SIMULATION ONLY posture and avoids persisting credentials.
 */

import { roleToPermissions } from './auth';
import type { Permission, UserSession } from './auth';

export interface SafetyReport {
  application_mode: string;
  simulation_only: boolean;
  hardware_integration_enabled: boolean;
  allow_external_modbus_writes: boolean;
  automatic_device_discovery_enabled: boolean;
  safety_status: string;
}

export interface PlantOverviewData {
  plant_name: string;
  active_power_mw: number | null;
  reactive_power_mvar: number | null;
  avail_charge_mw: number | null;
  avail_discharge_mw: number | null;
  total_energy_mwh: number | null;
  average_soc_pct: number | null;
  grid_frequency_hz: number | null;
  poi_voltage_kv: number | null;
  active_alarms_count: number;
  equipment_availability_pct: number;
  simulation_state: string;
  simulation_time_str: string;
  wall_clock_time_str: string;
}

export interface ControlResponse {
  success: boolean;
  status: string;
  engine_state?: string;
  message: string;
}

export interface SystemInfo {
  project_name: string;
  version: string;
  environment: string;
  safety: SafetyReport;
  engine: {
    status: string;
    mode: string;
    current_tick: number;
    is_running: boolean;
    /** The wall-clock pacing factor in force. Optional: an older backend
     *  does not report it, and the screen then says so rather than
     *  inventing a value. */
    speed_factor?: number;
    message: string;
  };
}

/** A row of the historian's time-series telemetry table. */
export interface HistorianTelemetryRecord {
  timestamp_ns: number;
  source_timestamp_ns: number;
  tag_id: string;
  equipment_id: string;
  value: number;
  unit: string;
  quality: string;
  source_type: string;
  simulation_run_id: string;
}

/** A row of the historian's traceable command audit log. */
export interface HistorianCommandRecord {
  command_id: string;
  timestamp_ns: number;
  requestor: string;
  target_equipment_id: string;
  requested_value: Record<string, unknown>;
  accepted_status: string;
  rejection_reason: string;
  resulting_response: Record<string, unknown> | null;
  simulation_run_id: string;
}

/** A row of the historian's alarm and event log. */
export interface HistorianAlarmRecord {
  event_id: string;
  timestamp_ns: number;
  equipment_id: string;
  severity: string;
  code: string;
  description: string;
  acknowledged: boolean;
  cleared: boolean;
  simulation_run_id: string;
}

/**
 * The degradation and warranty metrics recorded for one battery container.
 *
 * Every field is nullable because the historian stores whatever the recorder
 * produced: a container that has not been measured yet has no throughput, no
 * cycles and no temperature. `null` therefore means "not recorded", and the
 * screen has to say so rather than print a zero that reads like a measurement.
 */
export interface WarrantyMetrics {
  container_id: string;
  simulation_run_id: string;
  updated_at_ns: number;
  total_energy_throughput_wh: number | null;
  equivalent_full_cycles: number | null;
  max_temperature_recorded_c: number | null;
  time_above_45c_seconds: number | null;
  current_soh_pct: number | null;
}

/** The outcome of a read-only historian query that returns rows. */
export interface HistorianQueryResult<T> {
  /** True only when the backend answered with a success status. */
  ok: boolean;
  /** The HTTP status the backend answered with, or 0 for a transport failure. */
  status: number;
  /** The rows the backend returned; empty when the query failed. */
  records: T[];
  /** Why the query failed, in words an operator can act on. */
  error: string | null;
}

/** The outcome of a read-only warranty query. */
export interface WarrantyQueryResult {
  /**
   * True when the backend holds a warranty record for the container.
   *
   * A missing record is not a failure: the backend answers 404 when it holds
   * no metrics for a container, and that is a true statement about the
   * platform's state rather than an error the operator has to act on.
   */
  found: boolean;
  /** The record, when the backend holds one. */
  metrics: WarrantyMetrics | null;
  /** The HTTP status the backend answered with, or 0 for a transport failure. */
  status: number;
  /** Why the query failed, in words an operator can act on. */
  error: string | null;
}

/**
 * One piece of equipment of the running plant.
 *
 * A field the topology does not declare is `null`. The screen has to be able
 * to say "not specified" rather than print a placeholder that reads like a
 * configured value.
 */
export interface TopologyEquipment {
  equipment_id: string;
  equipment_type: string;
  manufacturer: string | null;
  plugin_id: string | null;
  illustrative: boolean;
  capacity_wh: number | null;
  rated_power_w: number | null;
  rated_apparent_power_va: number | null;
  nominal_voltage_v: number | null;
  specifications: Record<string, number>;
}

/** The topology of the plant the platform is running. */
export interface PlantTopology {
  /** False when no plant is attached to the running platform. */
  plant_configured: boolean;
  plant_id: string | null;
  plant_name: string | null;
  /** True when the plant's parameters are illustrative. */
  illustrative: boolean | null;
  rated_power_w: number | null;
  rated_energy_wh: number | null;
  /** The configuration file the plant was built from. */
  source_path: string | null;
  equipment: TopologyEquipment[];
  counts: Record<string, number>;
  /** Why the plant is not configured, when it is not. */
  message: string | null;
  safety: SafetyReport;
}

/** The outcome of a read-only topology query. */
export interface TopologyQueryResult {
  /** True only when the backend answered with a success status. */
  ok: boolean;
  /** The HTTP status the backend answered with, or 0 for a transport failure. */
  status: number;
  /** The topology the backend reported; null when the query failed. */
  topology: PlantTopology | null;
  /** Why the query failed, in words an operator can act on. */
  error: string | null;
}

export interface LoginRequest {
  username: string;
  password: string;
}
export interface TokenResponse {
  access_token: string;
  token_type: string;
  username: string;
  role: string;
  permissions: string[];
}

/**
 * In-memory platform session holder.
 *
 * The token is deliberately NOT persisted in localStorage/sessionStorage or cookies:
 * it is scoped to the live browser session and is cleared on page reload.
 */
class PlatformSession {
  #token: string | null = null;

  #user: UserSession | null = null;

  get token(): string | null {
    return this.#token;
  }

  get user(): UserSession | null {
    return this.#user;
  }

  get isAuthenticated(): boolean {
    return this.#token !== null;
  }

  setAuthenticated(user: UserSession, token: string): void {
    this.#user = user;
    this.#token = token;
  }

  clear(): void {
    this.#user = null;
    this.#token = null;
  }
}

/** Global platform session singleton, shared across API service and UI layers. */
export const platformSession = new PlatformSession();

const BASE_URL = '/api/v1';

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = platformSession.token;
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function fetchSystemHealth(): Promise<{ healthy: boolean; data?: SystemInfo }> {
  try {
    const res = await fetch(`${BASE_URL}/info`, { headers: authHeaders() });
    if (!res.ok) {
      return { healthy: false };
    }
    const data: SystemInfo = await res.json();
    return { healthy: true, data };
  } catch {
    return { healthy: false };
  }
}

export async function fetchPlantOverview(): Promise<PlantOverviewData | null> {
  try {
    const res = await fetch(`${BASE_URL}/overview`, { headers: authHeaders() });
    if (res.ok) {
      return await res.json();
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Build a query string from the parameters that were actually filled in.
 *
 * An empty filter is left out of the URL rather than sent as an empty
 * string: the backend reads an empty string as a filter value, which would
 * narrow the query to equipment whose identifier is the empty string and
 * return nothing.
 */
function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      search.set(key, String(value));
    }
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** A JSON response, with the reason it was not usable when it was not. */
interface RawJson<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error: string | null;
}

/**
 * Perform a read-only GET and decode its JSON body.
 *
 * A non-success status is reported with the backend's own explanation when it
 * sends one: the operator is told what the platform refused and why, not
 * only that a number appeared on the screen.
 */
async function getJson<T>(url: string): Promise<RawJson<T>> {
  try {
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) {
      let detail = `The backend answered with status ${res.status}.`;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === 'string') {
          detail = body.detail;
        }
      } catch {
        // The body is not JSON. The status code is what the operator needs.
      }
      return { ok: false, status: res.status, data: null, error: detail };
    }
    return { ok: true, status: res.status, data: (await res.json()) as T, error: null };
  } catch {
    return {
      ok: false,
      status: 0,
      data: null,
      error: 'Network error connecting to the backend API.',
    };
  }
}

/** The filters the historian's telemetry query accepts. */
export interface TelemetryQuery {
  equipment_id?: string;
  tag_id?: string;
  simulation_run_id?: string;
  start_time_ns?: number;
  end_time_ns?: number;
  sampling_step_ns?: number;
  limit?: number;
}

/**
 * Read historical telemetry rows from the historian.
 *
 * The historian is a read-only store from the screen's point of view: the
 * query asks for rows and the backend answers with the rows it holds.
 */
export async function fetchHistorianTelemetry(
  params: TelemetryQuery = {},
): Promise<HistorianQueryResult<HistorianTelemetryRecord>> {
  const query = buildQuery({ ...params });
  const res = await getJson<{ count: number; records: HistorianTelemetryRecord[] }>(
    `${BASE_URL}/historian/telemetry${query}`,
  );
  if (!res.ok || res.data === null) {
    return { ok: false, status: res.status, records: [], error: res.error };
  }
  return { ok: true, status: res.status, records: res.data.records, error: null };
}

/** The filters the historian's command audit query accepts. */
export interface CommandQuery {
  target_equipment_id?: string;
  simulation_run_id?: string;
  limit?: number;
}

/** Read the traceable command audit log from the historian. */
export async function fetchHistorianCommands(
  params: CommandQuery = {},
): Promise<HistorianQueryResult<HistorianCommandRecord>> {
  const query = buildQuery({ ...params });
  const res = await getJson<{ count: number; records: HistorianCommandRecord[] }>(
    `${BASE_URL}/historian/commands${query}`,
  );
  if (!res.ok || res.data === null) {
    return { ok: false, status: res.status, records: [], error: res.error };
  }
  return { ok: true, status: res.status, records: res.data.records, error: null };
}

/** The filters the historian's alarm and event query accepts. */
export interface AlarmQuery {
  equipment_id?: string;
  severity?: string;
  limit?: number;
}

/** Read the alarm and event log from the historian. */
export async function fetchHistorianAlarms(
  params: AlarmQuery = {},
): Promise<HistorianQueryResult<HistorianAlarmRecord>> {
  const query = buildQuery({ ...params });
  const res = await getJson<{ count: number; records: HistorianAlarmRecord[] }>(
    `${BASE_URL}/historian/alarms${query}`,
  );
  if (!res.ok || res.data === null) {
    return { ok: false, status: res.status, records: [], error: res.error };
  }
  return { ok: true, status: res.status, records: res.data.records, error: null };
}

/**
 * Read the warranty and degradation metrics of one battery container.
 *
 * The backend answers 404 when it holds no metrics for the container. That is
 * reported as "not found" rather than as an error, because the screen has to
 * be able to say that no warranty record exists — which is a different
 * statement from "the query failed".
 */
export async function fetchWarrantyMetrics(
  containerId: string,
): Promise<WarrantyQueryResult> {
  const encoded = encodeURIComponent(containerId);
  const res = await getJson<WarrantyMetrics>(`${BASE_URL}/historian/warranty/${encoded}`);
  if (res.ok && res.data !== null) {
    return { found: true, metrics: res.data, status: res.status, error: null };
  }
  if (res.status === 404) {
    return { found: false, metrics: null, status: 404, error: null };
  }
  return { found: false, metrics: null, status: res.status, error: res.error };
}

/**
 * Read the topology of the plant the platform is running.
 *
 * The endpoint is read-only: it publishes the plant that owns the engine and
 * cannot change it. A platform with no plant attached answers with a
 * topology whose `plant_configured` is false, which is a true statement
 * about the platform rather than an error.
 */
export async function fetchPlantTopology(): Promise<TopologyQueryResult> {
  const res = await getJson<PlantTopology>(`${BASE_URL}/topology`);
  if (!res.ok || res.data === null) {
    return { ok: false, status: res.status, topology: null, error: res.error };
  }
  return { ok: true, status: res.status, topology: res.data, error: null };
}

export async function dispatchSimulationControl(  action: string,
  payload: Record<string, unknown> = {},
): Promise<ControlResponse> {
  try {
    const res = await fetch(`${BASE_URL}/simulation/control`, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, ...payload }),
    });

    const data = await res.json();

    if (res.status === 200) {
      return {
        success: true,
        status: data.status || 'SUCCESS',
        engine_state: data.engine_state,
        message: data.message || 'Action executed successfully.',
      };
    } else if (res.status === 503) {
      return {
        success: false,
        status: 'NOT_CONNECTED',
        message: data.detail?.message || 'Simulation engine is not connected.',
      };
    } else if (res.status === 401 || res.status === 403) {
      return {
        success: false,
        status: 'UNAUTHORIZED',
        message: 'Authentication / permission required for simulation control.',
      };
    } else {
      return {
        success: false,
        status: 'FAILED',
        // A refused command states why it was refused, and the reason is
        // part of the detail. The backend sends it as a plain string for a
        // validation refusal and as an object for the rest, and the operator
        // must see which one they got.
        message:
          data.detail?.message ||
          (typeof data.detail === 'string' ? data.detail : 'Failed to execute control action.'),
      };
    }
  } catch {
    return {
      success: false,
      status: 'DISCONNECTED',
      message: 'Network error connecting to backend API.',
    };
  }
}

export async function login(payload: LoginRequest): Promise<TokenResponse | null> {
  try {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const data: TokenResponse = await res.json();
      return data;
    }
    return null;
  } catch {
    return null;
  }
}

export async function fetchUserDetails(token: string): Promise<UserSession | null> {
  try {
    const res = await fetch(`${BASE_URL}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      return null;
    }
    const user = await res.json();
    const role = user.role;
    const backendPermissions = Array.isArray(user.permissions)
      ? user.permissions.map((p: string): Permission => p as Permission)
      : [];
    const permissions = backendPermissions.length > 0
      ? new Set<Permission>(backendPermissions)
      : roleToPermissions(role);
    return { username: user.username, role, permissions };
  } catch {
    return null;
  }
}

export function logout(): void {
  platformSession.clear();
}
