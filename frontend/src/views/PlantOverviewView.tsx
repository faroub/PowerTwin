import React from 'react';

export const PlantOverviewView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Plant Overview</h1>
        <p className="view-subtitle">Utility-Scale BESS Operational Dashboard Shell</p>
      </div>

      <div className="notice-box">
        <strong>SIMULATION ONLY FOUNDATION (WP01):</strong> Plant topology, live telemetry rendering, and active power flow dynamics will be populated during physics model implementation (WP02+).
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Plant Name</div>
          <div className="card-value">PowerTwin Alpha</div>
          <div className="card-note">50 MW / 200 MWh Target Spec</div>
        </div>
        <div className="card">
          <div className="card-title">System Mode</div>
          <div className="card-value" style={{ color: '#ef4444' }}>SIMULATION ONLY</div>
          <div className="card-note">Hardware Connections Disabled</div>
        </div>
        <div className="card">
          <div className="card-title">Active Power</div>
          <div className="card-value">0.00 MW</div>
          <div className="card-note">Engine Idle</div>
        </div>
        <div className="card">
          <div className="card-title">Average SoC</div>
          <div className="card-value">50.0 %</div>
          <div className="card-note">Initial State</div>
        </div>
      </div>
    </div>
  );
};
