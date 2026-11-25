import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const ScenarioManagerView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Scenario Manager</h1>
        <p className="view-subtitle">Grid Fault & Market Dispatch Scenario Profile Runner</p>
      </div>

      <SimulatedDataNotice detail="Illustrative scenario profile of the simulation framework." />

      <div className="card">
        <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Active Scenario Profile</h3>
        <p style={{ color: '#94a3b8' }}>Reference Baseline Profile: Continuous 100 Hz Grid Pacing.</p>
      </div>
    </div>
  );
};
