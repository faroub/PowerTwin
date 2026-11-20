import React, { useState } from 'react';

interface SLDNode {
  id: string;
  name: string;
  type: string;
  status: 'RUNNING' | 'STANDBY' | 'FAULTED' | 'CLOSED' | 'OPEN';
  p_mw: number;
  q_mvar: number;
  voltage: string;
  soc?: number;
  alarms: number;
}

const mockNodes: SLDNode[] = [
  { id: 'C01', name: 'Container 01', type: 'BATTERY', status: 'RUNNING', p_mw: 1.25, q_mvar: 0.0, voltage: '1000V DC', soc: 65.0, alarms: 0 },
  { id: 'C02', name: 'Container 02', type: 'BATTERY', status: 'RUNNING', p_mw: 1.25, q_mvar: 0.0, voltage: '1000V DC', soc: 64.0, alarms: 0 },
  { id: 'C03', name: 'Container 03', type: 'BATTERY', status: 'RUNNING', p_mw: 1.25, q_mvar: 0.0, voltage: '1000V DC', soc: 65.0, alarms: 0 },
  { id: 'C04', name: 'Container 04', type: 'BATTERY', status: 'RUNNING', p_mw: 1.25, q_mvar: 0.0, voltage: '1000V DC', soc: 64.0, alarms: 0 },
  { id: 'PCS1', name: 'PCS Inverter 01-04', type: 'PCS', status: 'RUNNING', p_mw: 4.90, q_mvar: 0.50, voltage: '690V AC', alarms: 0 },
  { id: 'XFRM1', name: 'Transformer 10MVA', type: 'TRANSFORMER', status: 'RUNNING', p_mw: 4.86, q_mvar: 0.50, voltage: '690V / 13.8kV', alarms: 0 },
  { id: 'SWG1', name: 'MV Switchgear Breaker', type: 'SWITCHGEAR', status: 'CLOSED', p_mw: 4.86, q_mvar: 0.50, voltage: '13.8kV AC', alarms: 0 },
  { id: 'POI1', name: 'POI Boundary Meter', type: 'METER', status: 'RUNNING', p_mw: 4.86, q_mvar: 0.50, voltage: '13.8kV AC', alarms: 0 },
  { id: 'GRID1', name: '50 Hz Utility Grid', type: 'GRID', status: 'RUNNING', p_mw: 4.86, q_mvar: 0.50, voltage: '13.8kV AC', alarms: 0 },
];

export const SingleLineDiagramView: React.FC = () => {
  const [selectedNode, setSelectedNode] = useState<SLDNode | null>(mockNodes[0]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'RUNNING':
      case 'CLOSED':
        return '#22c55e';
      case 'STANDBY':
        return '#eab308';
      case 'FAULTED':
      case 'OPEN':
        return '#ef4444';
      default:
        return '#94a3b8';
    }
  };

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Electrical Single-Line Diagram (SLD)</h1>
        <p className="view-subtitle">Interactive Dynamic Electrical Topology Canvas</p>
      </div>

      <div style={{ display: 'flex', gap: '20px' }}>
        {/* SLD Canvas */}
        <div style={{ flex: 1, backgroundColor: '#1e293b', borderRadius: '8px', border: '1px solid #334155', padding: '24px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', alignItems: 'center' }}>
            {/* Battery Tier */}
            <div style={{ display: 'flex', gap: '12px' }}>
              {mockNodes.filter(n => n.type === 'BATTERY').map(n => (
                <div
                  key={n.id}
                  onClick={() => setSelectedNode(n)}
                  style={{
                    padding: '12px',
                    borderRadius: '6px',
                    backgroundColor: '#0f172a',
                    border: `2px solid ${getStatusColor(n.status)}`,
                    cursor: 'pointer',
                    minWidth: '130px',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{n.name}</div>
                  <div style={{ fontSize: '1rem', fontWeight: '700', color: '#22c55e', marginTop: '4px' }}>SoC: {n.soc}%</div>
                  <div style={{ fontSize: '0.75rem', color: '#38bdf8', marginTop: '2px' }}>{n.p_mw} MW</div>
                </div>
              ))}
            </div>

            <div style={{ color: '#38bdf8', fontWeight: 'bold' }}>↓ DC Bus (1000V DC) ↓</div>

            {/* PCS Tier */}
            <div
              onClick={() => setSelectedNode(mockNodes[4])}
              style={{
                padding: '14px 28px',
                borderRadius: '6px',
                backgroundColor: '#0f172a',
                border: `2px solid ${getStatusColor(mockNodes[4].status)}`,
                cursor: 'pointer',
                textAlign: 'center',
              }}
            >
              <div style={{ fontWeight: '700' }}>🔌 {mockNodes[4].name}</div>
              <div style={{ fontSize: '0.85rem', color: '#38bdf8' }}>P: {mockNodes[4].p_mw} MW | Q: {mockNodes[4].q_mvar} MVAR</div>
            </div>

            <div style={{ color: '#38bdf8', fontWeight: 'bold' }}>↓ AC Low-Voltage (690V AC) ↓</div>

            {/* Transformer Tier */}
            <div
              onClick={() => setSelectedNode(mockNodes[5])}
              style={{
                padding: '14px 28px',
                borderRadius: '6px',
                backgroundColor: '#0f172a',
                border: `2px solid ${getStatusColor(mockNodes[5].status)}`,
                cursor: 'pointer',
                textAlign: 'center',
              }}
            >
              <div style={{ fontWeight: '700' }}>🏭 {mockNodes[5].name}</div>
              <div style={{ fontSize: '0.85rem', color: '#94a3b8' }}>Step-Up (690V / 13.8kV)</div>
            </div>

            <div style={{ color: '#38bdf8', fontWeight: 'bold' }}>↓ MV Bus (13.8kV AC) ↓</div>

            {/* Switchgear Tier */}
            <div
              onClick={() => setSelectedNode(mockNodes[6])}
              style={{
                padding: '14px 28px',
                borderRadius: '6px',
                backgroundColor: '#0f172a',
                border: `2px solid ${getStatusColor(mockNodes[6].status)}`,
                cursor: 'pointer',
                textAlign: 'center',
              }}
            >
              <div style={{ fontWeight: '700' }}>⚡ Breaker: {mockNodes[6].status}</div>
            </div>

            <div style={{ color: '#38bdf8', fontWeight: 'bold' }}>↓ Point of Interconnection (POI) ↓</div>

            {/* POI & Grid */}
            <div style={{ display: 'flex', gap: '16px' }}>
              <div
                onClick={() => setSelectedNode(mockNodes[7])}
                style={{
                  padding: '12px 20px',
                  borderRadius: '6px',
                  backgroundColor: '#0f172a',
                  border: `2px solid ${getStatusColor(mockNodes[7].status)}`,
                  cursor: 'pointer',
                }}
              >
                <strong>📊 {mockNodes[7].name}</strong>
              </div>
              <div
                onClick={() => setSelectedNode(mockNodes[8])}
                style={{
                  padding: '12px 20px',
                  borderRadius: '6px',
                  backgroundColor: '#0f172a',
                  border: `2px solid ${getStatusColor(mockNodes[8].status)}`,
                  cursor: 'pointer',
                }}
              >
                <strong>🌐 {mockNodes[8].name}</strong>
              </div>
            </div>
          </div>
        </div>

        {/* Selected Equipment Telemetry Drawer */}
        {selectedNode && (
          <div style={{ width: '320px', backgroundColor: '#1e293b', borderRadius: '8px', border: '1px solid #334155', padding: '20px' }}>
            <h3 style={{ marginBottom: '16px', color: '#38bdf8' }}>{selectedNode.name}</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.9rem' }}>
              <div><strong>Type:</strong> {selectedNode.type}</div>
              <div><strong>Status:</strong> <span style={{ color: getStatusColor(selectedNode.status), fontWeight: 'bold' }}>{selectedNode.status}</span></div>
              <div><strong>Voltage:</strong> {selectedNode.voltage}</div>
              <div><strong>Active Power (P):</strong> {selectedNode.p_mw} MW</div>
              <div><strong>Reactive Power (Q):</strong> {selectedNode.q_mvar} MVAR</div>
              {selectedNode.soc !== undefined && <div><strong>Battery SoC:</strong> {selectedNode.soc}%</div>}
              <div><strong>Active Alarms:</strong> {selectedNode.alarms}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
