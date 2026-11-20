import React from 'react';

export const GridServicesView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Grid Services</h1>
        <p className="view-subtitle">Frequency Droop Response & Volt-VAR Regulation</p>
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Frequency Droop</div>
          <div className="card-value">5.0 %</div>
          <div className="card-note">Deadband +/- 0.03 Hz</div>
        </div>

        <div className="card">
          <div className="card-title">Volt-VAR Control</div>
          <div className="card-value">STANDBY</div>
          <div className="card-note">Automated POI Regulation</div>
        </div>
      </div>
    </div>
  );
};
