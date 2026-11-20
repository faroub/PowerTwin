import React from 'react';

export const PluginManagerView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Plugin Manager</h1>
        <p className="view-subtitle">Vendor Equipment and Controller Plugin Registry</p>
      </div>

      <div className="notice-box">
        <strong>PLUGIN MANAGER SHELL:</strong> Sandboxed plugin manifests, capability verification, and activation toggles will be enabled in WP03.
      </div>

      <div className="card">
        <div className="card-title">Loaded Plugins</div>
        <div className="card-value">0 Active</div>
        <p style={{ color: '#94a3b8', marginTop: '8px' }}>No vendor plugins loaded in foundation mode.</p>
      </div>
    </div>
  );
};
