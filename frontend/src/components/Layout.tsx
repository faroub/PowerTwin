import React, { useEffect, useState } from "react";
import { StatusBanner } from './StatusBanner';
import { Sidebar, ViewId } from './Sidebar';
import { fetchSystemHealth, SystemInfo } from '../services/api';
import { UserSession } from '../services/auth';

interface LayoutProps {
  /** Currently active HMI view id. */
  currentView: ViewId;
  /** View selection handler provided by the application. */
  onSelectView: (view: ViewId) => void;
  /** Children are the rendered view body. */
  children?: React.ReactNode;
  /**
   * Active in-memory platform session, if the user has consented and logged in.
   * Rendering only — the backend enforces permissions server-side.
   */
  user?: UserSession | null;
  /** Optional logout handler used to clear the in-memory platform session. */
  onLogout?: () => void;
}

export const Layout: React.FC<LayoutProps> = ({
  currentView,
  onSelectView,
  children,
  user,
  onLogout,
}) => {
  const [isOnline, setIsOnline] = useState<boolean>(false);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);

  useEffect(() => {
    let isMounted = true;
    const checkHealth = async () => {
      const res = await fetchSystemHealth();
      if (isMounted) {
        setIsOnline(res.healthy);
        if (res.healthy && res.data) {
          setSystemInfo(res.data);
        }
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 5000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="app-container">
      <StatusBanner
        isOnline={isOnline}
        systemInfo={systemInfo}
        username={user?.username}
        role={user?.role}
      />
      <div className="main-layout">
        <Sidebar currentView={currentView} onSelectView={onSelectView} />
        <main className="content-area">{children}</main>
      </div>
      <div className="safety-footer">
        SIMULATION ONLY | No hardware equipment is detected |
        {user?.username ? `Session: ${user.username} [${user.role}]` : 'No active session'}
        {onLogout && (
          <span style={{ color: '#ef4444', cursor: 'pointer', marginLeft: '8px' }} onClick={onLogout}>
            LOGOUT
          </span>
        )}
      </div>
    </div>
  );
};
