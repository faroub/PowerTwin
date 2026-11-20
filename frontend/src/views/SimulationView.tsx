import React, { useState } from 'react';
import { ConfirmationModal } from '../components/ConfirmationModal';

export const SimulationView: React.FC = () => {
  const [modalOpen, setModalOpen] = useState(false);
  const [actionName, setActionName] = useState('');

  const triggerControl = (name: string) => {
    setActionName(name);
    setModalOpen(true);
  };

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Simulation Control</h1>
        <p className="view-subtitle">Clock Control, Speed Multipliers, and Deterministic Reset</p>
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Engine Lifecycle State</div>
          <div className="card-value" style={{ color: '#22c55e' }}>RUNNING</div>
          <div className="card-note">100 Hz Tick Frequency</div>
        </div>

        <div className="card">
          <div className="card-title">Wall-Clock Speed Factor</div>
          <div className="card-value">1.0 x</div>
          <div className="card-note">Real-Time Pacing</div>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: '16px', color: '#38bdf8' }}>Engine Execution Controls</h3>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            onClick={() => triggerControl('Pause Engine')}
            style={{ padding: '10px 20px', borderRadius: '6px', backgroundColor: '#eab308', color: '#0f172a', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
          >
            PAUSE
          </button>
          <button
            onClick={() => triggerControl('Single Step (+10ms)')}
            style={{ padding: '10px 20px', borderRadius: '6px', backgroundColor: '#38bdf8', color: '#0f172a', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
          >
            SINGLE STEP (+10ms)
          </button>
          <button
            onClick={() => triggerControl('Reset Simulation Clock')}
            style={{ padding: '10px 20px', borderRadius: '6px', backgroundColor: '#ef4444', color: '#ffffff', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
          >
            RESET SIMULATION
          </button>
        </div>
      </div>

      <ConfirmationModal
        isOpen={modalOpen}
        title="Confirm Engine Control Action"
        actionDetails={`Are you sure you want to execute: ${actionName}?`}
        onConfirm={() => setModalOpen(false)}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
};
