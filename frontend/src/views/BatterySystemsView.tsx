import React from 'react';

export const BatterySystemsView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Battery Systems</h1>
        <p className="view-subtitle">Cell, Module, Rack, and Container Electro-Thermal Models</p>
      </div>

      <div className="notice-box">
        <strong>BATTERY DOMAIN SHELL:</strong> Equivalent circuit models (ECM), thermal diffusion, cell balancing, and degradation algorithms will be implemented in WP02+.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Battery Containers</div>
          <div className="card-value">0 / 4 Active</div>
          <div className="card-note">Configured via YAML</div>
        </div>
        <div className="card">
          <div className="card-title">Total Racks</div>
          <div className="card-value">0 Racks</div>
          <div className="card-note">16 Racks/Container Spec</div>
        </div>
        <div className="card">
          <div className="card-title">Max Cell Temp</div>
          <div className="card-value">25.0 °C</div>
          <div className="card-note">Ambient Baseline</div>
        </div>
      </div>
    </div>
  );
};
