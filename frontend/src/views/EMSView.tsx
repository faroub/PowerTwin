import React from 'react';

export const EMSView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Energy Management System (EMS)</h1>
        <p className="view-subtitle">Economic Dispatch, Peak Shaving, and Arbitrage Scenarios</p>
      </div>

      <div className="notice-box">
        <strong>EMS DISPATCH SHELL:</strong> High-level schedule engines and market arbitrage optimization scenarios will be implemented in WP02+.
      </div>

      <div className="card">
        <div className="card-title">Active Schedule Profile</div>
        <div className="card-value">NONE</div>
        <p style={{ color: '#94a3b8', marginTop: '8px' }}>EMS schedule runner standby.</p>
      </div>
    </div>
  );
};
