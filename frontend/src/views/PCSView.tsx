import React from 'react';

export const PCSView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">PCS / Inverters</h1>
        <p className="view-subtitle">Apparent Power Circle Clamping & 4-Value Setpoint Tracking</p>
      </div>

      <div className="notice-box">
        <strong>INVERTER DISPATCH TELEMETRY:</strong> Demonstrates P² + Q² ≤ S_max² capability circle clamping.
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <h3 style={{ marginBottom: '12px', color: '#38bdf8' }}>Explicit 4-Value Setpoint Distinction</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', textAlign: 'center' }}>
          <div style={{ padding: '12px', backgroundColor: '#0f172a', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>1. REQUESTED</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold' }}>5.00 MW</div>
          </div>
          <div style={{ padding: '12px', backgroundColor: '#0f172a', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>2. ACCEPTED</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#eab308' }}>5.00 MW</div>
          </div>
          <div style={{ padding: '12px', backgroundColor: '#0f172a', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>3. ACTUAL</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#22c55e' }}>4.92 MW</div>
          </div>
          <div style={{ padding: '12px', backgroundColor: '#0f172a', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>4. MEASURED</div>
            <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#38bdf8' }}>4.92 MW</div>
          </div>
        </div>
      </div>
    </div>
  );
};
