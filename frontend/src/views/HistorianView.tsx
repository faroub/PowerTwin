import React from 'react';

export const HistorianView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Historian & Trend Analysis</h1>
        <p className="view-subtitle">High-Resolution Time-Series Telemetry Querying</p>
      </div>

      <div className="notice-box">
        <strong>HISTORIAN SHELL:</strong> Multi-axis time-series charting wired to TimescaleDB continuous aggregates will be enabled in WP02+.
      </div>

      <div className="card" style={{ minHeight: '200px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <p style={{ color: '#64748b' }}>Historian Telemetry Chart Placeholder</p>
      </div>
    </div>
  );
};
