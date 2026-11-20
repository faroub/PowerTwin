import React from 'react';

export const BMSView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Master BMS Controller</h1>
        <p className="view-subtitle">Protection Thresholds, Permissives, and Current Limits</p>
      </div>

      <div className="notice-box">
        <strong>MASTER BMS CONTROLLER STATUS:</strong> Enforces voltage, current, and thermal limiters.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">BMS Contactors</div>
          <div className="card-value" style={{ color: '#22c55e' }}>CLOSED</div>
          <div className="card-note">Permissives OK</div>
        </div>

        <div className="card">
          <div className="card-title">Charge Current Limit (CCL)</div>
          <div className="card-value">1000.0 A</div>
          <div className="card-note">Max 1000 A Limit</div>
        </div>

        <div className="card">
          <div className="card-title">Discharge Current Limit (DCL)</div>
          <div className="card-value">1000.0 A</div>
          <div className="card-note">Max 1000 A Limit</div>
        </div>
      </div>
    </div>
  );
};
