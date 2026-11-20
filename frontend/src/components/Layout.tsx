import React, { useState, useEffect } from 'react';
import { StatusBanner } from './StatusBanner';
import { Sidebar, ViewId } from './Sidebar';
import { fetchSystemHealth, SystemInfo } from '../services/api';

interface LayoutProps {
  currentView: ViewId;
  onSelectView: (view: ViewId) => void;
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ currentView, onSelectView, children }) => {
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
      <StatusBanner isOnline={isOnline} systemInfo={systemInfo} />
      <div className="main-layout">
        <Sidebar currentView={currentView} onSelectView={onSelectView} />
        <main className="content-area">{children}</main>
      </div>
    </div>
  );
};
