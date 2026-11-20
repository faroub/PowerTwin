import React from 'react';

export const EquipmentControllerView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Equipment Controller</h1>
        <p className="view-subtitle">Local Device Control, Contactors, and Interlock State</p>
      </div>

      <div className="notice-box">
        <strong>EQUIPMENT CONTROLLER SHELL:</strong> Local hardware contactor sequencing and local protection interlocks will be populated in WP02+.
      </div>

      <div className="card">
        <div className="card-title">Device Safety Status</div>
        <div className="card-value" style={{ color: '#22c55e' }}>INTERLOCKS OK</div>
        <p style={{ color: '#94a3b8', marginTop: '8px' }}>Simulation-only safety boundary active.</p>
      </div>
    </div>
  );
};
