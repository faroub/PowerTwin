import React from 'react';

import { usePlantTelemetry } from '../services/hooks';

export const AlarmsView: React.FC = () => {
  const { data: telemetry, loading } = usePlantTelemetry();
  const connected = telemetry?.simulation_state !== 'NOT_CONNECTED';
  const alarmsCount = telemetry?.active_alarms_count ?? 0;

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Alarms & Events</h1>
        <p className="view-subtitle">System Fault Log and Event Processing</p>
      </div>

      <div className="card">
        <h3 style={{ color: alarmsCount === 0 ? '#22c55e' : '#ef4444', marginBottom: '12px' }}>
          Active Alarms ({loading ? '—' : alarmsCount})
        </h3>
        <p style={{ color: '#94a3b8' }}>
          {loading ? '—' : connected
            ? alarmsCount === 0
              ? 'No active faults or critical alarms recorded.'
              : `${alarmsCount} active alarms recorded in plant telemetry.`
            : 'No active faults or critical alarms recorded.'}
        </p>
      </div>
    </div>
  );
};
