import React from 'react';

export type ViewId =
  | 'overview'
  | 'sld'
  | 'battery'
  | 'pcs'
  | 'grid'
  | 'eq_controller'
  | 'ppc'
  | 'ems'
  | 'alarms'
  | 'historian'
  | 'simulation'
  | 'configuration'
  | 'plugins';

interface SidebarProps {
  currentView: ViewId;
  onSelectView: (view: ViewId) => void;
}

const navItems: { id: ViewId; label: string; icon: string }[] = [
  { id: 'overview', label: 'Plant Overview', icon: '📊' },
  { id: 'sld', label: 'Single-Line Diagram', icon: '⚡' },
  { id: 'battery', label: 'Battery Systems', icon: '🔋' },
  { id: 'pcs', label: 'PCS & Inverters', icon: '🔌' },
  { id: 'grid', label: 'Grid & POI', icon: '🌐' },
  { id: 'eq_controller', label: 'Equipment Controller', icon: '🕹️' },
  { id: 'ppc', label: 'Power Plant Ctrl (PPC)', icon: '⚙️' },
  { id: 'ems', label: 'EMS Dispatch', icon: '📈' },
  { id: 'alarms', label: 'Alarms & Events', icon: '🔔' },
  { id: 'historian', label: 'Historian', icon: '💾' },
  { id: 'simulation', label: 'Simulation Control', icon: '⏱️' },
  { id: 'configuration', label: 'Configuration', icon: '🛠️' },
  { id: 'plugins', label: 'Plugin Manager', icon: '🧩' },
];

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onSelectView }) => {
  return (
    <aside className="sidebar">
      {navItems.map((item) => (
        <div
          key={item.id}
          className={`nav-item ${currentView === item.id ? 'active' : ''}`}
          onClick={() => onSelectView(item.id)}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </div>
      ))}
    </aside>
  );
};
