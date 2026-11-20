import React from 'react';

export const BatterySystemsView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Battery Systems</h1>
        <p className="view-subtitle">Container & Rack Electro-Thermal Telemetry</p>
      </div>

      <div className="notice-box">
        <strong>CONTAINER TELEMETRY MONITORING:</strong> Operating parameters for reference battery containers.
      </div>

      <div className="grid-cards">
        {[1, 2, 3, 4].map((id) => (
          <div key={id} className="card">
            <div className="card-title">Container {String(id).padStart(2, '0')}</div>
            <div className="card-value" style={{ color: '#22c55e' }}>64.5 % SoC</div>
            <div style={{ marginTop: '12px', fontSize: '0.85rem', color: '#94a3b8' }}>
              <div>Voltage: 1000.0 V DC</div>
              <div>Current: +250.0 A</div>
              <div>Temperature: 25.4 °C</div>
              <div>Racks: 16 / 16 Operational</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
