import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const ConfigurationView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Plant Configuration</h1>
        <p className="view-subtitle">YAML Topology Definitions and Parameter Inspector</p>
      </div>

      <SimulatedDataNotice detail="Illustrative YAML topology templates and their validated parameters." />

      <div className="card">
        <div className="card-title">Active Configuration</div>
        <div className="card-value">configs/dev.yaml</div>
        <p style={{ color: '#94a3b8', marginTop: '8px' }}>Development default topology template.</p>
      </div>
    </div>
  );
};
