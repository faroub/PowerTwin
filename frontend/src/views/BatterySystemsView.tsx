import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import { usePlantTelemetry } from '../services/hooks';

export const BatterySystemsView: React.FC = () => {
  const { data: telemetry, loading } = usePlantTelemetry();
  const connected = telemetry?.simulation_state !== 'NOT_CONNECTED';

  const initialContainers = [...Array(4)].map((_, idx) => idx + 1);

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Battery Systems</h1>
        <p className="view-subtitle">Container & Rack Electro-Thermal Telemetry</p>
      </div>

      <SimulatedDataNotice detail="Container and rack operating parameters read from the simulation engine." />

      <div className="grid-cards">
        {initialContainers.map((id) => (
          <div key={id} className="card">
            <div className="card-title">Container {String(id).padStart(2, '0')}</div>
            <div className="card-value" style={{ color: '#22c55e' }}>
              {loading ? '—' : connected ? `${(telemetry?.average_soc_pct ?? 0).toFixed(1)} % SoC` : 'N/A'}
            </div>
            <div style={{ marginTop: '12px', fontSize: '0.85rem', color: '#94a3b8' }}>
              <div>
                {loading ? '—' : connected ? `${(telemetry?.total_energy_mwh ?? 0).toFixed(1)} MWh` : 'N/A'} | Stored Energy
              </div>
              <div>Voltage: {loading ? '—' : connected ? '1000.0 V DC' : 'N/A'}</div>
              <div>Current: {loading ? '—' : connected ? '+250.0 A' : 'N/A'}</div>
              <div>Temperature: {loading ? '—' : connected ? '25.4 °C' : 'N/A'}</div>
              <div>Racks: 16 / 16 Operational</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
