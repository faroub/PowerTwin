import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const TransformersSwitchgearView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Transformers & Switchgear</h1>
        <p className="view-subtitle">Balance of Plant (BoP) Transformation and Breaker Interlocks</p>
      </div>

      <SimulatedDataNotice detail="Illustrative balance-of-plant ratings and breaker interlocks of the reference plant." />

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Transformer Rating</div>
          <div className="card-value">11.0 MVA</div>
          <div className="card-note">Turns Ratio: 690V / 13.8kV</div>
        </div>

        <div className="card">
          <div className="card-title">MV Switchgear Breaker</div>
          <div className="card-value" style={{ color: '#22c55e' }}>CLOSED</div>
          <div className="card-note">Interlocks OK | Rated 2000A</div>
        </div>
      </div>
    </div>
  );
};
