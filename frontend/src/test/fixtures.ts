/**
 * Representative payloads for the component suite.
 *
 * The values are illustrative test fixtures, not plant data. They carry the
 * safety posture the platform reports in simulation mode, so that a test that
 * asserts on the rendered HMI is asserting on the posture the platform
 * actually claims: simulation only, no hardware integration, no external
 * Modbus writes, no automatic device discovery.
 */

import type { PlantTopology, SystemInfo } from '../services/api';
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
    speed_factor: 1.0,
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

/**
 * A backend `/topology` response for the reference plant.
 *
 * The inventory mirrors the shape the real endpoint publishes: a field the
 * topology does not declare is `null` rather than a placeholder, and every
 * item carries the illustrative label the plant's parameters require.
 */
export const REFERENCE_PLANT_TOPOLOGY: PlantTopology = {
  plant_configured: true,
  plant_id: 'REF_PLANT_10MW_20MWH',
  plant_name: 'PowerTwin Reference 10 MW / 20 MWh BESS Plant',
  illustrative: true,
  rated_power_w: 10_000_000,
  rated_energy_wh: 20_000_000,
  source_path: 'configs/reference_10mw_20mwh.yaml',
  equipment: [
    {
      equipment_id: 'CONTAINER_01',
      equipment_type: 'BATTERY_SYSTEM',
      manufacturer: 'Reference Cell Co',
      plugin_id: 'generic_battery',
      illustrative: true,
      capacity_wh: 5_000_000,
      rated_power_w: null,
      rated_apparent_power_va: null,
      nominal_voltage_v: 1331,
      specifications: { racks_count: 4, initial_soc_pct: 50 },
    },
    {
      equipment_id: 'PCS_01',
      equipment_type: 'PCS',
      manufacturer: 'Reference Inverter Co',
      plugin_id: 'generic_pcs',
      illustrative: true,
      capacity_wh: null,
      rated_power_w: 2_500_000,
      rated_apparent_power_va: 2_777_778,
      nominal_voltage_v: 690,
      specifications: { dc_voltage_min_v: 900, dc_voltage_max_v: 1500 },
    },
    {
      equipment_id: 'XFRM_MAIN_01',
      equipment_type: 'TRANSFORMER',
      // The topology declares no vendor for the transformer, so the endpoint
      // publishes none. A placeholder would read as a configured vendor.
      manufacturer: null,
      plugin_id: null,
      illustrative: true,
      capacity_wh: null,
      rated_power_w: null,
      rated_apparent_power_va: 12_000_000,
      nominal_voltage_v: 33_000,
      specifications: { primary_voltage_v: 33_000, secondary_voltage_v: 690 },
    },
    {
      equipment_id: 'AUX_SYS_01',
      equipment_type: 'AUXILIARY_SYSTEM',
      manufacturer: null,
      plugin_id: 'generic_auxiliary',
      illustrative: true,
      capacity_wh: null,
      rated_power_w: 25_000,
      rated_apparent_power_va: null,
      nominal_voltage_v: null,
      specifications: {},
    },
  ],
  counts: {
    BATTERY_SYSTEM: 4,
    PCS: 4,
    TRANSFORMER: 1,
    AUXILIARY_SYSTEM: 1,
  },
  message: null,
  safety: HEALTHY_SYSTEM_INFO.safety,
};
