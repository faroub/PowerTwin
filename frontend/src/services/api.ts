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
  active_power_mw: number;
  reactive_power_mvar: number;
  avail_charge_mw: number;
  avail_discharge_mw: number;
  total_energy_mwh: number;
  average_soc_pct: number;
  grid_frequency_hz: number;
  poi_voltage_kv: number;
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

export async function fetchPlantOverview(): Promise<PlantOverviewData> {
  try {
    const res = await fetch('/api/v1/overview');
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // Fallback simulated metrics for HMI demonstration
  }
  return {
    plant_name: "PowerTwin Reference 10 MW / 20 MWh Plant",
    active_power_mw: 4.85,
    reactive_power_mvar: 0.50,
    avail_charge_mw: 10.00,
    avail_discharge_mw: 10.00,
    total_energy_mwh: 20.00,
    average_soc_pct: 64.5,
    grid_frequency_hz: 50.02,
    poi_voltage_kv: 13.81,
    active_alarms_count: 0,
    equipment_availability_pct: 100.0,
    simulation_state: "RUNNING",
    simulation_time_str: "00:15:30.450.000",
    wall_clock_time_str: new Date().toLocaleTimeString(),
  };
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
