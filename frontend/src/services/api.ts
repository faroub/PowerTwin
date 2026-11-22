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

export async function fetchSystemHealth(): Promise<{ healthy: boolean; data?: SystemInfo }> {
  try {
    const res = await fetch('/api/v1/info');
    if (!res.ok) {
      return { healthy: false };
    }
    const data: SystemInfo = await res.json();
    return { healthy: true, data };
  } catch {
    return { healthy: false };
  }
}

export async function fetchPlantOverview(token?: string): Promise<PlantOverviewData | null> {
  try {
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch('/api/v1/overview', { headers });
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
  token?: string
): Promise<ControlResponse> {
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch('/api/v1/simulation/control', {
      method: 'POST',
      headers,
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
