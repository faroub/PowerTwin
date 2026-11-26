import React, { useEffect, useState } from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import { fetchPlantTopology, PlantTopology, TopologyEquipment } from '../services/api';

/**
 * Format a rating for the operator.
 *
 * The unit is chosen from the magnitude, and a value the topology does not
 * declare is reported as absent rather than as a zero: a "0.0 MW" rating
 * reads as a measurement of a plant that cannot discharge, which is a
 * different statement from "the topology declares no rating".
 */
function formatPower(watts: number | null): string {
  if (watts === null) {
    return 'NOT SPECIFIED';
  }
  if (Math.abs(watts) >= 1_000_000) {
    return `${(watts / 1_000_000).toFixed(2)} MW`;
  }
  if (Math.abs(watts) >= 1_000) {
    return `${(watts / 1_000).toFixed(1)} kW`;
  }
  return `${watts.toFixed(0)} W`;
}

function formatEnergy(wattHours: number | null): string {
  if (wattHours === null) {
    return 'NOT SPECIFIED';
  }
  if (Math.abs(wattHours) >= 1_000_000) {
    return `${(wattHours / 1_000_000).toFixed(2)} MWh`;
  }
  return `${wattHours.toFixed(0)} Wh`;
}

/**
 * The rating a piece of equipment is summarised by.
 *
 * A container is summarised by its energy capacity, a PCS by its active
 * power, and everything else by its apparent power. An item with none of
 * those ratings says so.
 */
function summaryOf(item: TopologyEquipment): string {
  if (item.capacity_wh !== null) {
    return formatEnergy(item.capacity_wh);
  }
  if (item.rated_power_w !== null) {
    return formatPower(item.rated_power_w);
  }
  if (item.rated_apparent_power_va !== null) {
    return `${(item.rated_apparent_power_va / 1_000_000).toFixed(2)} MVA`;
  }
  return 'NOT SPECIFIED';
}

/**
 * The Plant Configuration screen.
 *
 * The screen shows the plant the platform is actually running: its
 * identity, its ratings, and the inventory of its equipment. Everything it
 * shows is read from the running platform's read-only topology endpoint.
 *
 * The screen never falls back on a hard-coded plant. A platform with no
 * plant attached says so, and a backend that cannot be reached says that
 * too — printing the reference plant's properties when the backend is
 * silent would be exactly the fabrication this screen replaced.
 */
export const PlantConfigurationView: React.FC = () => {
  const [topology, setTopology] = useState<PlantTopology | null>(null);
  const [reachable, setReachable] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const read = async () => {
      const result = await fetchPlantTopology();
      if (!mounted) {
        return;
      }
      setTopology(result.topology);
      setReachable(result.ok);
      setError(result.error);
    };
    read();
    return () => {
      mounted = false;
    };
  }, []);

  const configured = topology?.plant_configured === true;
  const equipment = topology?.equipment ?? [];

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Plant Configuration</h1>
        <p className="view-subtitle">The Topology of the Running Plant</p>
      </div>

      <SimulatedDataNotice detail="The topology, ratings and equipment inventory of the plant the platform is running, as the platform reports them." />

      {!reachable && (
        <div className="card" style={{ marginBottom: '16px', borderColor: '#eab308' }}>
          <h3 style={{ color: '#eab308', marginBottom: '8px' }}>The platform did not answer</h3>
          <p style={{ color: '#94a3b8', fontSize: '0.9rem', margin: 0 }}>
            {error ?? 'The topology could not be read.'} Nothing below is verified: the
            screen shows no plant rather than a substitute one.
          </p>
        </div>
      )}

      {reachable && !configured && (
        <div className="card" style={{ marginBottom: '16px' }}>
          <h3 style={{ color: '#eab308', marginBottom: '8px' }}>No plant is attached</h3>
          <p style={{ color: '#94a3b8', fontSize: '0.9rem', margin: 0 }}>
            {topology?.message ??
              'The platform is running without a plant. The topology is built at start-up.'}
          </p>
        </div>
      )}

      {configured && topology && (
        <>
          <div className="card" style={{ marginBottom: '16px' }}>
            <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Plant</h3>
            <div style={{ color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.8 }}>
              <div>
                <strong>Name:</strong> {topology.plant_name ?? 'UNAVAILABLE'}
              </div>
              <div>
                <strong>Identifier:</strong> {topology.plant_id ?? 'UNAVAILABLE'}
              </div>
              <div>
                <strong>Rated Power:</strong> {formatPower(topology.rated_power_w)}
              </div>
              <div>
                <strong>Rated Energy:</strong> {formatEnergy(topology.rated_energy_wh)}
              </div>
              <div>
                <strong>Topology File:</strong> {topology.source_path ?? 'BUILT IN CODE'}
              </div>
              <div>
                <strong>Parameters:</strong>{' '}
                <span style={{ color: topology.illustrative ? '#eab308' : '#22c55e' }}>
                  {topology.illustrative
                    ? 'ILLUSTRATIVE — NOT VALIDATED AGAINST AUTHORITATIVE DATA'
                    : 'DECLARED AS VALIDATED'}
                </span>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>
              Equipment Inventory ({equipment.length})
            </h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                <thead>
                  <tr style={{ color: '#94a3b8', textAlign: 'left' }}>
                    <th style={{ padding: '6px 10px', borderBottom: '1px solid #334155' }}>
                      Equipment
                    </th>
                    <th style={{ padding: '6px 10px', borderBottom: '1px solid #334155' }}>Type</th>
                    <th style={{ padding: '6px 10px', borderBottom: '1px solid #334155' }}>
                      Manufacturer
                    </th>
                    <th style={{ padding: '6px 10px', borderBottom: '1px solid #334155' }}>
                      Rating
                    </th>
                    <th style={{ padding: '6px 10px', borderBottom: '1px solid #334155' }}>
                      Parameters
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {equipment.map((item) => (
                    <tr key={item.equipment_id} style={{ color: '#e2e8f0' }}>
                      <td style={{ padding: '6px 10px', borderBottom: '1px solid #1e293b' }}>
                        {item.equipment_id}
                      </td>
                      <td style={{ padding: '6px 10px', borderBottom: '1px solid #1e293b' }}>
                        {item.equipment_type}
                      </td>
                      <td style={{ padding: '6px 10px', borderBottom: '1px solid #1e293b' }}>
                        {item.manufacturer ?? 'NOT SPECIFIED'}
                      </td>
                      <td style={{ padding: '6px 10px', borderBottom: '1px solid #1e293b' }}>
                        {summaryOf(item)}
                      </td>
                      <td style={{ padding: '6px 10px', borderBottom: '1px solid #1e293b' }}>
                        <span style={{ color: item.illustrative ? '#eab308' : '#22c55e' }}>
                          {item.illustrative ? 'ILLUSTRATIVE' : 'VALIDATED'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {equipment.length === 0 && (
              <p style={{ color: '#eab308', fontSize: '0.85rem', marginTop: '12px', marginBottom: 0 }}>
                The plant reports no equipment. The platform is running with an empty
                inventory, which it is reporting rather than hiding.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
};
