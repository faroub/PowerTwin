import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const WarrantyMetricsView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Warranty Metrics</h1>
        <p className="view-subtitle">Battery Degradation & Equivalent Full Cycles (EFC)</p>
      </div>

      <SimulatedDataNotice detail="Illustrative degradation and warranty figures. They are not measurements of any battery." />

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Total Energy Throughput</div>
          <div className="card-value">124.5 MWh</div>
          <div className="card-note">Lifetime Discharge</div>
        </div>

        <div className="card">
          <div className="card-title">Equivalent Full Cycles</div>
          <div className="card-value">6.2 EFC</div>
          <div className="card-note">Calculated Cycles</div>
        </div>

        <div className="card">
          <div className="card-title">Current State of Health</div>
          <div className="card-value" style={{ color: '#22c55e' }}>100.0 % SOH</div>
          <div className="card-note">Warranty Baseline</div>
        </div>
      </div>
    </div>
  );
};
