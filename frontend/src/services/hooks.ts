/**
 * Telemetry hook shared by all HMI views.
 *
 * All network requests carry the active in-memory platform session token, and all
 * rendering happens off the backend source of truth. The hook exposes the engine and
 * safety posture alongside the plant telemetry so the UI can gate interactive controls.
 */

import { useEffect, useState } from 'react';

import { SafetyReport, SystemInfo, platformSession } from './api';

export interface PlantTelemetry {
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
  safety: SafetyReport;
  engine: SystemInfo['engine'];
}

export interface TelemetryHookState {
  data: PlantTelemetry | null;
  isConnected: boolean;
  loading: boolean;
  error: string | null;
}

/**
 * Poll the Plant Overview SCADA endpoint and expose the resulting telemetry bundle.
 *
 * The polling rate is fixed because the backend launcher buffer drives telemetry
 * sampling; faster polling only increases the chance of reading stale frames.
 */
export function usePlantTelemetry(
  pollingIntervalMs = 2000
): TelemetryHookState {
  const [data, setData] = useState<PlantTelemetry | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const token = platformSession.token;
      const res = await fetch('/api/v1/overview', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        setError(`Overview request failed with status ${res.status}`);
        return;
      }
      const raw: PlantTelemetry = await res.json();
      setData(raw);
      setError(null);
    } catch (err) {
      setError('Network error connecting to backend API.');
      void err;
    }
  };

  useEffect(() => {
    let isMounted = true;
    refresh();
    setLoading(false);
    const interval = setInterval(() => {
      if (isMounted) {
        refresh();
      }
    }, pollingIntervalMs);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [pollingIntervalMs]);

  return {
    data,
    loading,
    error,
    isConnected: data !== null && data.simulation_state !== 'NOT_CONNECTED',
  };
}
