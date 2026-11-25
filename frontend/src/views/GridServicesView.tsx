import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const GridServicesView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Grid Services</h1>
        <p className="view-subtitle">Frequency Droop Response & Volt-VAR Regulation</p>
      </div>

      <SimulatedDataNotice detail="Illustrative parameters of the simulated grid-service and market framework." />

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Frequency Droop</div>
          <div className="card-value">5.0 %</div>
          <div className="card-note">Deadband +/- 0.03 Hz</div>
        </div>

        <div className="card">
          <div className="card-title">Volt-VAR Control</div>
          <div className="card-value">STANDBY</div>
          <div className="card-note">Automated POI Regulation</div>
        </div>
      </div>
    </div>
  );
};
