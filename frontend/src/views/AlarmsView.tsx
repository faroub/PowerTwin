import React from 'react';

export const AlarmsView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Alarms & Events</h1>
        <p className="view-subtitle">System Fault Log and Event Processing</p>
      </div>

      <div className="card">
        <h3 style={{ color: '#22c55e', marginBottom: '12px' }}>Active Alarms (0)</h3>
        <p style={{ color: '#94a3b8' }}>No active faults or critical alarms recorded.</p>
      </div>
    </div>
  );
};
