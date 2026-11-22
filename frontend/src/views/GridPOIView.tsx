import React from 'react';

import { usePlantTelemetry } from '../services/hooks';

export const GridPOIView: React.FC = () => {
  const { data: telemetry, loading } = usePlantTelemetry();
  const connected = telemetry?.simulation_state !== 'NOT_CONNECTED';

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Grid & POI</h1>
        <p className="view-subtitle">Synthetic Grid Model & POI Meter Monitoring</p>
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">POI Flow Direction</div>
          <div className="card-value" style={{ color: '#22c55e' }}>
            {loading ? '—' : connected ? 'EXPORTING (+P)' : 'N/A'}
          </div>
          <div className="card-note">
            {loading ? '—' : connected ? `+${telemetry?.active_power_mw?.toFixed(2) ?? 0} MW Discharging` : 'N/A'}
          </div>
        </div>

        <div className="card">
          <div className="card-title">Grid Operating State</div>
          <div className="card-value">{loading ? '—' : connected ? 'GRID_CONNECTED' : 'N/A'}</div>
          <div className="card-note">
            {loading ? '—' : connected
              ? `${telemetry?.grid_frequency_hz?.toFixed(2) ?? 0}.00 Hz Nominal`
              : 'N/A'}
          </div>
        </div>
      </div>
    </div>
  );
};
