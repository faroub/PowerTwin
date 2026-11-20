import React from 'react';

export const SimulationView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Simulation Control</h1>
        <p className="view-subtitle">Clock Control, Speed Multipliers, and Deterministic Replay</p>
      </div>

      <div className="notice-box">
        <strong>SIMULATION ENGINE CONTROL SHELL:</strong> Pause, single-step (+10ms), reset, and speed scaling will be connected to the engine tick loop in WP02+.
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Simulation Tick Rate</div>
          <div className="card-value">100 Hz</div>
          <div className="card-note">10 ms Step Size</div>
        </div>
        <div className="card">
          <div className="card-title">Engine State</div>
          <div className="card-value">STOPPED</div>
          <div className="card-note">Foundation Shell</div>
        </div>
      </div>
    </div>
  );
};
