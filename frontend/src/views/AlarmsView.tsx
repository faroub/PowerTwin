import React from 'react';

export const AlarmsView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Alarms & Events</h1>
        <p className="view-subtitle">System Fault Log and Event Processing</p>
      </div>

      <div className="notice-box">
        <strong>ALARMS SHELL:</strong> Real-time alarm banner and event log filtering will be connected to TimescaleDB events in WP02+.
      </div>

      <div className="card">
        <div className="card-title">Active Critical Alarms</div>
        <div className="card-value" style={{ color: '#22c55e' }}>0 ACTIVE</div>
        <p style={{ color: '#94a3b8', marginTop: '8px' }}>System operating normally in simulation foundation mode.</p>
      </div>
    </div>
  );
};
