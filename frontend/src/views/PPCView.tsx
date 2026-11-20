import React from 'react';

export const PPCView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Power Plant Controller (PPC)</h1>
        <p className="view-subtitle">Active/Reactive Power Regulation, Frequency Droop, and Volt-VAR</p>
      </div>

      <div className="notice-box">
        <strong>PPC CONTROL SHELL:</strong> Closed-loop P-f droop, Volt-VAR curves, and POI ramp rate limiters will be implemented in WP02+.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">PPC Mode</div>
          <div className="card-value">MANUAL</div>
          <div className="card-note">Direct Operator Target</div>
        </div>
        <div className="card">
          <div className="card-title">Frequency Droop</div>
          <div className="card-value">5.0 %</div>
          <div className="card-note">Standard Grid Code Spec</div>
        </div>
      </div>
    </div>
  );
};
