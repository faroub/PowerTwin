import React from 'react';

export const SingleLineDiagramView: React.FC = () => {
  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Electrical Single-Line Diagram (SLD)</h1>
        <p className="view-subtitle">Interactive Plant Electrical Topology Visualization</p>
      </div>

      <div className="notice-box">
        <strong>SLD VISUALIZATION SHELL:</strong> The interactive SVG electrical topology canvas (Container -&gt; PCS -&gt; Transformer -&gt; MV Switchgear -&gt; POI Meter) will be wired to real-time simulation state in WP02+.
      </div>

      <div className="card" style={{ minHeight: '300px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', border: '1px dashed #334155' }}>
        <div style={{ fontSize: '3rem', marginBottom: '12px' }}>⚡</div>
        <h3 style={{ color: '#94a3b8' }}>Electrical Topology Canvas</h3>
        <p style={{ color: '#64748b', fontSize: '0.9rem', marginTop: '4px' }}>[ Grid POI ] --- [ Step-Up Transformer ] --- [ MV Switchgear ] --- [ PCS Inverters ] --- [ Battery Racks ]</p>
      </div>
    </div>
  );
};
