import React, { useState, useEffect, useRef } from 'react';

import { ConfirmationModal } from '../components/ConfirmationModal';
import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import { fetchSystemHealth, dispatchSimulationControl, ControlResponse } from '../services/api';

/**
 * The wall-clock pacing bounds the backend enforces. The screen refuses a
 * factor outside them without sending it, and the backend refuses it again
 * if it is sent: the screen is a convenience, the platform is the authority.
 */
export const MIN_SPEED_FACTOR = 0;
export const MAX_SPEED_FACTOR = 100;

/** A control action the operator has asked for but not yet confirmed. */
interface PendingAction {
  /** The name the confirmation dialog shows. */
  name: string;
  /** The action the control endpoint understands. */
  action: string;
  /** The extra fields the action carries, such as a speed factor. */
  payload: Record<string, unknown>;
}

export const SimulationView: React.FC = () => {
  const [engineState, setEngineState] = useState<string>('UNKNOWN');
  const [speedFactor, setSpeedFactor] = useState<number | null>(null);
  const [requestedFactor, setRequestedFactor] = useState<string>('1');
  // A ref, not state: the engine read that seeds the field is asynchronous,
  // and a state value captured by the closure that started the read would be
  // the value from before the request — stale by the time the answer
  // arrives, and liable to overwrite what the operator has typed since.
  const factorEditedRef = useRef<boolean>(false);
  const [factorError, setFactorError] = useState<string>('');
  const [modalOpen, setModalOpen] = useState<boolean>(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [feedback, setFeedback] = useState<ControlResponse | null>(null);

  /**
   * Read the engine state and the pacing factor in force.
   *
   * The factor is read from the engine, not from what this screen last
   * asked for: the factor in force is the one that is pacing the clock.
   */
  const refreshEngine = async () => {
    const health = await fetchSystemHealth();
    if (health.healthy && health.data?.engine) {
      setEngineState(health.data.engine.status || 'NOT_CONNECTED');
      const factor = health.data.engine.speed_factor ?? null;
      setSpeedFactor(factor);
      // The field starts on the factor in force, so that a request the
      // operator did not edit asks for the pacing that is already running
      // instead of silently resetting it. A field the operator has edited
      // is theirs: the engine's answer never overwrites what they typed.
      if (!factorEditedRef.current && factor !== null) {
        setRequestedFactor(String(factor));
      }
    } else {
      setEngineState('NOT_CONNECTED');
      setSpeedFactor(null);
    }
  };

  useEffect(() => {
    refreshEngine();
  }, []);

  const triggerControl = (name: string, action: string, payload: Record<string, unknown> = {}) => {
    setPending({ name, action, payload });
    setModalOpen(true);
  };

  /**
   * Validate the requested speed factor before it is dispatched.
   *
   * A factor that is not a number, or that lies outside the permitted
   * range, is refused here with a reason. The backend refuses it as well;
   * refusing it here means the operator is told why before a request is
   * made rather than after it is rejected.
   */
  const requestSpeedChange = () => {
    const parsed = Number(requestedFactor);
    if (requestedFactor.trim() === '' || !Number.isFinite(parsed)) {
      setFactorError(`'${requestedFactor}' is not a speed factor.`);
      return;
    }
    if (parsed < MIN_SPEED_FACTOR || parsed > MAX_SPEED_FACTOR) {
      setFactorError(
        `A speed factor must be between ${MIN_SPEED_FACTOR} and ${MAX_SPEED_FACTOR}; ${parsed} was entered.`,
      );
      return;
    }
    setFactorError('');
    triggerControl(`Set Speed Factor (${parsed}x)`, 'SET_SPEED', { speed_factor: parsed });
  };

  const handleConfirmAction = async () => {
    setModalOpen(false);
    if (!pending) {
      return;
    }
    const result = await dispatchSimulationControl(pending.action, pending.payload);
    setFeedback(result);
    if (result.engine_state) {
      setEngineState(result.engine_state);
    }
    // The factor that is now in force is the engine's answer, not the one
    // that was requested, so the card is read again after every action.
    await refreshEngine();
  };

  const factorLabel =
    speedFactor === null
      ? 'UNKNOWN'
      : speedFactor === 0
      ? 'MAX (unpaced)'
      : `${speedFactor.toFixed(1)} x`;

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Simulation Control</h1>
        <p className="view-subtitle">Engine Lifecycle, Clock Control, and Deterministic Reset</p>
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
          <div className="card-value">{factorLabel}</div>
          <div className="card-note">
            {speedFactor === null
              ? 'The engine does not report a pacing factor'
              : 'Real-Time Pacing in force'}
          </div>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: '16px', color: '#38bdf8' }}>Engine Execution Controls</h3>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <button
            onClick={() => triggerControl('Start Engine', 'START')}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#22c55e',
              color: '#0f172a',
              border: 'none',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            START
          </button>
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
            onClick={() => triggerControl('Stop Engine', 'STOP')}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#f97316',
              color: '#0f172a',
              border: 'none',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            STOP
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

      <div className="card">
        <h3 style={{ marginBottom: '12px', color: '#38bdf8' }}>Wall-Clock Pacing</h3>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          <label htmlFor="speed-factor" style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>
            Speed factor (0 to {MAX_SPEED_FACTOR}, 0 = unpaced)
          </label>
          <input
            id="speed-factor"
            type="number"
            min={MIN_SPEED_FACTOR}
            max={MAX_SPEED_FACTOR}
            step={0.1}
            value={requestedFactor}
            onChange={(event) => {
              setRequestedFactor(event.target.value);
              factorEditedRef.current = true;
              setFactorError('');
            }}
            style={{
              padding: '8px 10px',
              borderRadius: '6px',
              border: '1px solid #334155',
              backgroundColor: '#0f172a',
              color: '#f8fafc',
              width: '110px',
            }}
          />
          <button
            onClick={requestSpeedChange}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#a78bfa',
              color: '#0f172a',
              border: 'none',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            SET SPEED
          </button>
        </div>
        {factorError && (
          <p style={{ marginTop: '12px', marginBottom: 0, color: '#ef4444', fontSize: '0.9rem' }}>
            {factorError}
          </p>
        )}
      </div>

      <ConfirmationModal
        isOpen={modalOpen}
        title="Confirm Engine Control Action"
        actionDetails={`Are you sure you want to execute: ${pending ? pending.name : ''}?`}
        onConfirm={handleConfirmAction}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
};
