import React, { useState, useEffect } from 'react';

import { ConfirmationModal } from '../components/ConfirmationModal';
import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import { fetchSystemHealth, dispatchSimulationControl, ControlResponse } from '../services/api';

export const SimulationView: React.FC = () => {
  const [engineState, setEngineState] = useState<string>('UNKNOWN');
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [actionName, setActionName] = useState<string>('');
  const [actionEnum, setActionEnum] = useState<string>('');
  const [feedback, setFeedback] = useState<ControlResponse | null>(null);
  

  useEffect(() => {
    const checkEngine = async () => {
      const health = await fetchSystemHealth();
      if (health.healthy && health.data?.engine) {
        setEngineState(health.data.engine.status || 'NOT_CONNECTED');
      } else {
        setEngineState('NOT_CONNECTED');
      }
    };
    checkEngine();

  }, []);

  const triggerControl = (name: string, actEnum: string) => {
    setActionName(name);
    setActionEnum(actEnum);
    setModalOpen(true);
  };

  const handleConfirmAction = async () => {
    setModalOpen(false);
    const result = await dispatchSimulationControl(actionEnum, {});
    setFeedback(result);
    if (result.engine_state) {
      setEngineState(result.engine_state);
    }
  };

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Simulation Control</h1>
        <p className="view-subtitle">Clock Control, Speed Multipliers, and Deterministic Reset</p>
      </div>

      <SimulatedDataNotice detail="Engine control actions. They act on the in-memory simulation only." />

      {feedback && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '6px',
            marginBottom: '16px',
            backgroundColor: feedback.success ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)',
            border: `1px solid ${feedback.success ? '#22c55e' : '#ef4444'}`,
            color: feedback.success ? '#22c55e' : '#ef4444',
            fontSize: '0.9rem',
          }}
        >
          <strong>[{feedback.status}]</strong> {feedback.message}
        </div>
      )}

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Engine Lifecycle State</div>
          <div
            className="card-value"
            style={{
              color:
                engineState === 'RUNNING'
                  ? '#22c55e'
                  : engineState === 'PAUSED'
                  ? '#eab308'
                  : '#ef4444',
            }}
          >
            {engineState}
          </div>
          <div className="card-note">Live Engine Status</div>
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
            onClick={() => triggerControl('Pause Engine', 'PAUSE')}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#eab308',
              color: '#0f172a',
              border: 'none',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            PAUSE
          </button>
          <button
            onClick={() => triggerControl('Single Step (+10ms)', 'STEP')}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#38bdf8',
              color: '#0f172a',
              border: 'none',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            SINGLE STEP (+10ms)
          </button>
          <button
            onClick={() => triggerControl('Reset Simulation Clock', 'RESET')}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#ef4444',
              color: '#ffffff',
              border: 'none',
              cursor: 'pointer',
              fontWeight: 'bold',
            }}
          >
            RESET SIMULATION
          </button>
        </div>
      </div>

      <ConfirmationModal
        isOpen={modalOpen}
        title="Confirm Engine Control Action"
        actionDetails={`Are you sure you want to execute: ${actionName}?`}
        onConfirm={handleConfirmAction}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
};
