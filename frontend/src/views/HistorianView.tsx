import React from 'react';

export const HistorianView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Historian</h1>
        <p className="view-subtitle">Time-Series Telemetry Querying & Configurable Sampling</p>
      </div>

      <div className="notice-box">
        <strong>TIMESCALEDB QUERY ENGINE:</strong> Retrieves historical time-series telemetry with configurable sampling steps.
      </div>

      <div className="card">
        <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Time-Series Query Controls</h3>
        <div style={{ color: '#94a3b8', fontSize: '0.9rem' }}>
          Sampling: 100ms | Range: Last 1 Hour | Database: PostgreSQL / TimescaleDB
        </div>
      </div>
    </div>
  );
};
