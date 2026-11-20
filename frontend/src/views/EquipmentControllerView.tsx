import React, { useState } from 'react';
import { ConfirmationModal } from '../components/ConfirmationModal';

export const EquipmentControllerView: React.FC = () => {
  const [modalOpen, setModalOpen] = useState(false);
  const [actionType, setActionType] = useState<string>('');

  const triggerAction = (type: string) => {
    setActionType(type);
    setModalOpen(true);
  };

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Equipment Controller (Layer A)</h1>
        <p className="view-subtitle">Device Startup/Shutdown Sequencing and Interlocks</p>
      </div>

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Controller State</div>
          <div className="card-value" style={{ color: '#22c55e' }}>RUNNING</div>
          <div className="card-note">Permissives OK</div>
        </div>

        <div className="card">
          <div className="card-title">Watchdog Heartbeat</div>
          <div className="card-value">OK</div>
          <div className="card-note">&lt; 5s Timeout</div>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: '16px', color: '#38bdf8' }}>Equipment Control Actions</h3>
        <div style={{ display: 'flex', gap: '12px' }}>
          <button
            onClick={() => triggerAction('Execute Startup Sequence')}
            style={{ padding: '10px 20px', borderRadius: '6px', backgroundColor: '#22c55e', color: '#0f172a', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
          >
            STARTUP SEQUENCE
          </button>
          <button
            onClick={() => triggerAction('Execute Shutdown Sequence')}
            style={{ padding: '10px 20px', borderRadius: '6px', backgroundColor: '#eab308', color: '#0f172a', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
          >
            SHUTDOWN SEQUENCE
          </button>
          <button
            onClick={() => triggerAction('Emergency Stop Trip')}
            style={{ padding: '10px 20px', borderRadius: '6px', backgroundColor: '#ef4444', color: '#ffffff', border: 'none', fontWeight: 'bold', cursor: 'pointer' }}
          >
            EMERGENCY STOP (E-STOP)
          </button>
        </div>
      </div>

      <ConfirmationModal
        isOpen={modalOpen}
        title="Confirm Equipment Control Action"
        actionDetails={`Are you sure you want to execute: ${actionType}?`}
        onConfirm={() => setModalOpen(false)}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
};
