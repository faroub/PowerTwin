import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const EMSView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Energy Management System (EMS - Layer C)</h1>
        <p className="view-subtitle">Economic Dispatch & Feasibility Validation</p>
      </div>

      <SimulatedDataNotice detail="EMS runs physical feasibility verification on all setpoints before dispatching to PPC." />

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Active EMS Mode</div>
          <div className="card-value">MANUAL_DISPATCH</div>
          <div className="card-note">Target SoC: 50.0%</div>
        </div>

        <div className="card">
          <div className="card-title">Dispatch Feasibility</div>
          <div className="card-value" style={{ color: '#22c55e' }}>FEASIBLE</div>
          <div className="card-note">Battery Headroom OK</div>
        </div>
      </div>
    </div>
  );
};
