import React from 'react';
import { SystemInfo } from '../services/api';

interface StatusBannerProps {
  isOnline: boolean;
  systemInfo: SystemInfo | null;
  username?: string;
  role?: string;
}

export const StatusBanner: React.FC<StatusBannerProps> = ({ isOnline, systemInfo, username, role }) => {
  return (
    <div className="top-bar">
      <div className="brand-title">
        ⚡ PowerTwin BESS Platform
      </div>

      <div className="safety-badge">
        MODE: {systemInfo?.safety?.application_mode || 'SIMULATION ONLY'}
      </div>

      <div className="status-pills">
        <div className={`status-pill ${isOnline ? 'online' : 'offline'}`}>
          <span className={`dot ${isOnline ? 'online' : 'offline'}`}></span>
          API: {isOnline ? 'CONNECTED' : 'DISCONNECTED'}
        </div>
        <div className="status-pill online">
          <span className="dot online"></span>
          SAFETY: GUARDRAILS ACTIVE
        </div>
        {username && (
          <div className="status-pill online">
            <span className="dot online"></span>
            {role && <span>{role}</span>} User: {username}
          </div>
        )}
      </div>
    </div>
  );
};
