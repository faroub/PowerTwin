import React from 'react';

export const GridPOIView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Grid & Point of Interconnection (POI)</h1>
        <p className="view-subtitle">Grid Frequency, POI Voltage, and Power Flow Simulation</p>
      </div>

      <div className="notice-box">
        <strong>GRID & POI DOMAIN SHELL:</strong> Synthetic grid sags, frequency deviations, and step-up transformer loss calculations will be implemented in WP02+.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Grid Frequency</div>
          <div className="card-value">60.00 Hz</div>
          <div className="card-note">Nominal Grid Reference</div>
        </div>
        <div className="card">
          <div className="card-title">POI Bus Voltage</div>
          <div className="card-value">13.8 kV</div>
          <div className="card-note">Medium Voltage Interconnection</div>
        </div>
      </div>
    </div>
  );
};
