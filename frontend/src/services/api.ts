export interface SafetyReport {
  application_mode: string;
  simulation_only: boolean;
  hardware_integration_enabled: boolean;
  allow_external_modbus_writes: boolean;
  automatic_device_discovery_enabled: boolean;
  safety_status: string;
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
