import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const SystemSettingsView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">System Settings</h1>
        <p className="view-subtitle">Application Configuration and Safety Invariants</p>
      </div>

      <SimulatedDataNotice detail="Application configuration and safety invariants of the running platform." />

      <div className="card">
        <h3 style={{ color: '#ef4444', marginBottom: '12px' }}>Non-Negotiable Safety Invariants</h3>
        <div style={{ color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.6 }}>
          <div><strong>Application Mode:</strong> SIMULATION ONLY</div>
          <div><strong>Hardware Integration:</strong> DISABLED</div>
          <div><strong>External Modbus Writes:</strong> DISABLED</div>
          <div><strong>Automatic Device Discovery:</strong> DISABLED</div>
        </div>
      </div>
    </div>
  );
};
