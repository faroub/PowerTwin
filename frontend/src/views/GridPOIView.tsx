import React from 'react';

export const GridPOIView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Grid & POI</h1>
        <p className="view-subtitle">Synthetic Grid Model & POI Meter Monitoring</p>
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">POI Flow Direction</div>
          <div className="card-value" style={{ color: '#22c55e' }}>EXPORTING (+P)</div>
          <div className="card-note">+4.86 MW Discharging</div>
        </div>

        <div className="card">
          <div className="card-title">Grid Operating State</div>
          <div className="card-value">GRID_CONNECTED</div>
          <div className="card-note">50.00 Hz Nominal</div>
        </div>
      </div>
    </div>
  );
};
