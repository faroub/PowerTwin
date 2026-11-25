import React from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';

export const EquipmentLibraryView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Equipment Library</h1>
        <p className="view-subtitle">Catalog of Validated Battery & Inverter Specifications</p>
      </div>

      <SimulatedDataNotice detail="Illustrative specifications for cells, racks, containers and PCS inverters." />

      <div className="card">
        <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Asset Specifications Catalog</h3>
        <p style={{ color: '#94a3b8' }}>Contains model specifications for cells, racks, containers, and PCS inverters.</p>
      </div>
    </div>
  );
};
