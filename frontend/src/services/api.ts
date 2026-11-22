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
    message: string;
  };
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

export async function dispatchSimulationControl(
  action: string,
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
        message: data.detail?.message || 'Failed to execute control action.',
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
