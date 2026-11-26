import React from 'react';

export type ViewId =
  | 'overview'
  | 'plant_config'
  | 'sld'
  | 'battery'
  | 'bms'
  | 'pcs'
  | 'xfrm_swg'
  | 'grid'
  | 'eq_controller'
  | 'ppc'
  | 'ems'
  | 'grid_services'
  | 'alarms'
  | 'historian'
  | 'warranty'
  | 'simulation'
  | 'scenario'
  | 'equipment_lib'
  | 'plugins'
  | 'settings';

interface SidebarProps {
  currentView: ViewId;
  onSelectView: (view: ViewId) => void;
}

const navItems: { id: ViewId; label: string; icon: string }[] = [
  { id: 'overview', label: 'Plant Overview', icon: '📊' },
  { id: 'plant_config', label: 'Plant Configuration', icon: '🏗️' },
  { id: 'sld', label: 'Single-Line Diagram', icon: '⚡' },
  { id: 'battery', label: 'Battery Systems', icon: '🔋' },
  { id: 'bms', label: 'BMS', icon: '🛡️' },
  { id: 'pcs', label: 'PCS / Inverters', icon: '🔌' },
  { id: 'xfrm_swg', label: 'Transformers & Switchgear', icon: '🏭' },
  { id: 'grid', label: 'Grid & POI', icon: '🌐' },
  { id: 'eq_controller', label: 'Equipment Controller', icon: '🕹️' },
  { id: 'ppc', label: 'Power Plant Ctrl (PPC)', icon: '⚙️' },
  { id: 'ems', label: 'EMS Dispatch', icon: '📈' },
  { id: 'grid_services', label: 'Grid Services', icon: '📡' },
  { id: 'alarms', label: 'Alarms & Events', icon: '🔔' },
  { id: 'historian', label: 'Historian', icon: '💾' },
  { id: 'warranty', label: 'Warranty Metrics', icon: '📑' },
  { id: 'simulation', label: 'Simulation Control', icon: '⏱️' },
  { id: 'scenario', label: 'Scenario Manager', icon: '🎯' },
  { id: 'equipment_lib', label: 'Equipment Library', icon: '📚' },
  { id: 'plugins', label: 'Plugin Manager', icon: '🧩' },
  { id: 'settings', label: 'System Settings', icon: '🔧' },
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
