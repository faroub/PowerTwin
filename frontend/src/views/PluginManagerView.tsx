import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const PluginManagerView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Plugin Manager</h1>
        <p className="view-subtitle">Registered Vendor Equipment Plugins & Manifest Registry</p>
      </div>

      <SimulatedDataNotice detail="Illustrative summary of the vendor plugins registered in the platform." />

      <div className="grid-cards">
        <div className="card">
          <div className="card-title">Registered Plugins</div>
          <div className="card-value">4 Plugins</div>
          <div className="card-note">API Version 0.1.0</div>
        </div>
      </div>
    </div>
  );
};
