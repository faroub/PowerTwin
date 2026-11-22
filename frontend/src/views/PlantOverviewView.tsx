import React, { useState, useEffect } from 'react';
import { fetchPlantOverview, PlantOverviewData } from '../services/api';

export const PlantOverviewView: React.FC = () => {
  const [overview, setOverview] = useState<PlantOverviewData | null>(null);

  useEffect(() => {
    let isMounted = true;
    const loadData = async () => {
      const data = await fetchPlantOverview();
      if (isMounted) setOverview(data);
    };
    loadData();
    const interval = setInterval(loadData, 2000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const isConnected = overview && overview.simulation_state !== 'NOT_CONNECTED';

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Plant Overview</h1>
        <p className="view-subtitle">Utility-Scale BESS Operational Dashboard</p>
      </div>

      <div className="notice-box">
        <strong>SCADA TELEMETRY MONITORING (SIMULATED DATA ONLY):</strong> Real-time operational state metrics streamed from the central simulation engine.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Plant Active Power</div>
          <div className="card-value" style={{ color: '#38bdf8' }}>
            {isConnected && overview?.active_power_mw !== null ? `${overview.active_power_mw.toFixed(2)} MW` : 'N/A'}
          </div>
          <div className="card-note">Net Export (+MW Discharge)</div>
        </div>

        <div className="card">
          <div className="card-title">Plant Reactive Power</div>
          <div className="card-value" style={{ color: '#38bdf8' }}>
            {isConnected && overview?.reactive_power_mvar !== null ? `${overview.reactive_power_mvar.toFixed(2)} MVAR` : 'N/A'}
          </div>
          <div className="card-note">+VAR Supplying</div>
        </div>

        <div className="card">
          <div className="card-title">Avail. Charge / Discharge</div>
          <div className="card-value">
            {isConnected && overview?.avail_charge_mw !== null && overview?.avail_discharge_mw !== null
              ? `-${overview.avail_charge_mw.toFixed(1)} / +${overview.avail_discharge_mw.toFixed(1)} MW`
              : 'N/A'}
          </div>
          <div className="card-note">Headroom Limits</div>
        </div>

        <div className="card">
          <div className="card-title">Average SoC / Energy</div>
          <div className="card-value" style={{ color: '#22c55e' }}>
            {isConnected && overview?.average_soc_pct !== null && overview?.total_energy_mwh !== null
              ? `${overview.average_soc_pct.toFixed(1)} % (${overview.total_energy_mwh.toFixed(1)} MWh)`
              : 'N/A'}
          </div>
          <div className="card-note">Plant Stored Energy</div>
        </div>

        <div className="card">
          <div className="card-title">Grid Freq / POI Voltage</div>
          <div className="card-value">
            {isConnected && overview?.grid_frequency_hz !== null && overview?.poi_voltage_kv !== null
              ? `${overview.grid_frequency_hz.toFixed(2)} Hz | ${overview.poi_voltage_kv.toFixed(2)} kV`
              : 'N/A'}
          </div>
          <div className="card-note">POI Bus Metrics</div>
        </div>

        <div className="card">
          <div className="card-title">Active Alarms / Availability</div>
          <div className="card-value" style={{ color: overview?.active_alarms_count === 0 ? '#22c55e' : '#ef4444' }}>
            {isConnected
              ? `${overview?.active_alarms_count} Alarms | ${overview?.equipment_availability_pct.toFixed(0)}%`
              : 'NOT CONNECTED'}
          </div>
          <div className="card-note">System Availability</div>
        </div>
      </div>

      <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>SIMULATION CLOCK: </span>
          <strong style={{ color: '#38bdf8', fontFamily: 'monospace', fontSize: '1.1rem' }}>
            {overview?.simulation_time_str || '00:00:00.000.000'}
          </strong>
        </div>
        <div>
          <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>WALL-CLOCK TIME: </span>
          <strong style={{ color: '#f8fafc', fontFamily: 'monospace', fontSize: '1.1rem' }}>
            {overview?.wall_clock_time_str || '--:--:--'}
          </strong>
        </div>
      </div>
    </div>
  );
};
