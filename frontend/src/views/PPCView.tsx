import React from 'react';

export const PPCView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Power Plant Controller (PPC - Layer B)</h1>
        <p className="view-subtitle">POI Power Regulation & Unit Power Allocation</p>
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Priority Mode</div>
          <div className="card-value" style={{ color: '#38bdf8' }}>ACTIVE_POWER_PRIORITY</div>
          <div className="card-note">P Priority over Q</div>
        </div>

        <div className="card">
          <div className="card-title">Ramp Rate Limit</div>
          <div className="card-value">10.0 MW/s</div>
          <div className="card-note">Active Power Ramp Bound</div>
        </div>
      </div>
    </div>
  );
};
