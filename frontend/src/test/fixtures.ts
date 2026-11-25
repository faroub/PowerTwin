/**
 * Representative payloads for the component suite.
 *
 * The values are illustrative test fixtures, not plant data. They carry the
 * safety posture the platform reports in simulation mode, so that a test that
 * asserts on the rendered HMI is asserting on the posture the platform
 * actually claims: simulation only, no hardware integration, no external
 * Modbus writes, no automatic device discovery.
 */

import type { SystemInfo } from '../services/api';
import type { PlantTelemetry } from '../services/hooks';

export const HEALTHY_SYSTEM_INFO: SystemInfo = {
  project_name: 'PowerTwin BESS Platform',
  version: '1.0.0',
  environment: 'test',
  safety: {
    application_mode: 'SIMULATION ONLY',
    simulation_only: true,
    hardware_integration_enabled: false,
    allow_external_modbus_writes: false,
    automatic_device_discovery_enabled: false,
    safety_status: 'ACTIVE_SIMULATION_GUARDRAILS_ENFORCED',
  },
  engine: {
    status: 'RUNNING',
    mode: 'REALTIME',
    current_tick: 12345,
    is_running: true,
    message: 'The simulation engine is running.',
  },
};

export const DISCONNECTED_SYSTEM_INFO: SystemInfo = {
  ...HEALTHY_SYSTEM_INFO,
  engine: {
    ...HEALTHY_SYSTEM_INFO.engine,
    status: 'NOT_CONNECTED',
    is_running: false,
    message: 'The simulation engine is not connected.',
  },
};

export const CONNECTED_TELEMETRY: PlantTelemetry = {
  plant_name: 'Reference Plant',
  active_power_mw: 4.25,
  reactive_power_mvar: 1.5,
  avail_charge_mw: 5.0,
  avail_discharge_mw: 5.0,
  total_energy_mwh: 12.75,
  average_soc_pct: 63.5,
  grid_frequency_hz: 50.0,
  poi_voltage_kv: 33.0,
  active_alarms_count: 0,
  equipment_availability_pct: 100,
  simulation_state: 'RUNNING',
  simulation_time_str: '00:01:23.450.000',
  wall_clock_time_str: '09:15:42',
  safety: HEALTHY_SYSTEM_INFO.safety,
  engine: HEALTHY_SYSTEM_INFO.engine,
};

export const DISCONNECTED_TELEMETRY: PlantTelemetry = {
  ...CONNECTED_TELEMETRY,
  simulation_state: 'NOT_CONNECTED',
  active_alarms_count: 3,
  equipment_availability_pct: 75,
};

/** A backend `/auth/login` response. */
export const TOKEN_RESPONSE = {
  access_token: 'test-access-token',
  token_type: 'bearer',
  username: 'engineer',
  role: 'ENGINEER',
  permissions: ['READ_TELEMETRY', 'READ_CONFIG', 'MODIFY_SIMULATION'],
};

/** A backend `/auth/me` response. */
export const USER_DETAILS = {
  username: 'engineer',
  role: 'ENGINEER',
  permissions: ['READ_TELEMETRY', 'READ_CONFIG', 'MODIFY_SIMULATION'],
};
