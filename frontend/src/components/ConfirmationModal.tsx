import React from 'react';

interface ConfirmationModalProps {
  isOpen: boolean;
  title: string;
  actionDetails: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmationModal: React.FC<ConfirmationModalProps> = ({
  isOpen,
  title,
  actionDetails,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(15, 23, 42, 0.85)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
      }}
    >
      <div
        style={{
          backgroundColor: '#1e293b',
          border: '1px solid #ef4444',
          borderRadius: '8px',
          padding: '24px',
          maxWidth: '480px',
          width: '90%',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <span style={{ fontSize: '1.75rem' }}>⚠️</span>
          <h3 style={{ margin: 0, color: '#ef4444', fontSize: '1.25rem' }}>{title}</h3>
        </div>

        <div
          style={{
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '6px',
            padding: '12px',
            marginBottom: '16px',
            fontSize: '0.85rem',
            color: '#f8fafc',
            lineHeight: 1.5,
          }}
        >
          <strong>SIMULATION ACTION CONFIRMATION:</strong>
          <p style={{ marginTop: '4px', margin: 0 }}>{actionDetails}</p>
        </div>

        <p style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '20px' }}>
          Note: All control actions operate exclusively on the in-memory simulation instance. Zero real equipment is targeted.
        </p>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button
            onClick={onCancel}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              backgroundColor: '#334155',
              color: '#f8fafc',
              border: 'none',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            CANCEL
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              backgroundColor: '#ef4444',
              color: '#ffffff',
              border: 'none',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            CONFIRM & EXECUTE
          </button>
        </div>
      </div>
    </div>
  );
};
