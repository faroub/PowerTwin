import React from 'react';

export const PCSView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Power Conversion Systems (PCS)</h1>
        <p className="view-subtitle">Inverter Models, Efficiency Curves, and PQ Limit Diagram</p>
      </div>

      <div className="notice-box">
        <strong>PCS DOMAIN SHELL:</strong> Active/reactive power actuation, IGBT switching loss calculation, and thermal derating will be implemented in WP02+.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">PCS Units</div>
          <div className="card-value">0 / 10 Units</div>
          <div className="card-note">5 MW Unit Capacity</div>
        </div>
        <div className="card">
          <div className="card-title">Inverter Efficiency</div>
          <div className="card-value">98.5 %</div>
          <div className="card-note">Nominal Curve Peak</div>
        </div>
        <div className="card">
          <div className="card-title">Operating Mode</div>
          <div className="card-value">STANDBY</div>
          <div className="card-note">Grid-Following Default</div>
        </div>
      </div>
    </div>
  );
};
