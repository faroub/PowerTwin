import React, { useState } from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import {
  fetchWarrantyMetrics,
  WarrantyMetrics,
  WarrantyQueryResult,
  WarrantyStatus,
} from '../services/api';

/**
 * The container the screen asks about until the operator names another one.
 *
 * `CONTAINER_01` is the identifier of the first container of the reference
 * plant. It is a starting point for the query, not a claim that the
 * platform holds metrics for it.
 */
const DEFAULT_CONTAINER_ID = 'CONTAINER_01';

/**
 * How the warranty verdict is shown.
 *
 * The verdict is a statement about where the container stands against its
 * warranty band, so it is colour-coded: green while there is room left, red
 * once the band is reached, and grey when the platform holds no state of
 * health to judge. `UNKNOWN` is a real answer and is never dressed up as a
 * measurement.
 */
function verdictOf(status: WarrantyStatus): { label: string; colour: string; note: string } {
  switch (status) {
    case 'WITHIN_WARRANTY':
      return {
        label: 'WITHIN WARRANTY',
        colour: '#22c55e',
        note: 'The container is above the state of health its warranty band requires.',
      };
    case 'AT_END_OF_LIFE':
      return {
        label: 'AT END OF LIFE',
        colour: '#ef4444',
        note: 'The container has reached the end of its warranty band.',
      };
    default:
      return {
        label: 'UNKNOWN',
        colour: '#94a3b8',
        note: 'The platform holds no state of health for this container, so it cannot say where the container stands.',
      };
  }
}

/**
 * Render a simulation timestamp as hours, minutes, seconds and milliseconds.
 *
 * The historian stores nanoseconds since the start of the run. Printing the
 * raw number would be unreadable; printing a wall-clock date would be
 * wrong, because the timestamp belongs to the simulation clock and not to
 * the calendar.
 */
function formatSimulationTime(timeNs: number): string {
  if (!Number.isFinite(timeNs) || timeNs < 0) {
    return '—';
  }
  const totalMs = Math.floor(timeNs / 1e6);
  const ms = totalMs % 1000;
  const totalSeconds = Math.floor(totalMs / 1000);
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  const pad = (value: number, width = 2) => String(value).padStart(width, '0');
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}.${pad(ms, 3)}`;
}

/** Render a measured value, or say plainly that nothing was recorded. */
function measured(value: number | null, suffix: string, digits = 2): string {
  return value === null || value === undefined ? 'NOT RECORDED' : `${value.toFixed(digits)} ${suffix}`;
}

export const WarrantyMetricsView: React.FC = () => {
  const [containerId, setContainerId] = useState<string>(DEFAULT_CONTAINER_ID);
  const [runId, setRunId] = useState<string>('');
  const [result, setResult] = useState<WarrantyQueryResult | null>(null);
  const [running, setRunning] = useState<boolean>(false);
  const [formError, setFormError] = useState<string>('');

  const inputStyle = {
    padding: '8px 10px',
    borderRadius: '6px',
    border: '1px solid #334155',
    backgroundColor: '#0f172a',
    color: '#f8fafc',
    width: '190px',
  };

  const runQuery = async () => {
    const container = containerId.trim();
    if (container === '') {
      setFormError('A container identifier is required.');
      return;
    }
    setFormError('');
    setRunning(true);
    setResult(await fetchWarrantyMetrics(container, runId));
    setRunning(false);
  };

  const metrics: WarrantyMetrics | null = result?.metrics ?? null;
  const verdict = verdictOf(metrics?.warranty_status ?? 'UNKNOWN');

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Warranty Metrics</h1>
        <p className="view-subtitle">Battery Degradation & Equivalent Full Cycles (EFC)</p>
      </div>

      <SimulatedDataNotice detail="The warranty and degradation metrics the historian holds for a battery container. A container with no recorded metrics is reported as such." />

      <div className="card" style={{ marginBottom: '16px' }}>
        <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Container</h3>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>
            <div style={{ marginBottom: '4px' }}>Container ID</div>
            <input
              type="text"
              value={containerId}
              onChange={(event) => setContainerId(event.target.value)}
              placeholder={DEFAULT_CONTAINER_ID}
              style={inputStyle}
            />
          </label>
          <label style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>
            <div style={{ marginBottom: '4px' }}>Simulation Run ID (optional)</div>
            <input
              type="text"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              placeholder="latest"
              style={inputStyle}
            />
          </label>
          <button
            onClick={runQuery}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              backgroundColor: '#38bdf8',
              color: '#0f172a',
              border: 'none',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            QUERY METRICS
          </button>
        </div>
        {formError && (
          <p style={{ marginTop: '12px', marginBottom: 0, color: '#ef4444', fontSize: '0.9rem' }}>
            {formError}
          </p>
        )}
      </div>

      {running && (
        <div className="card">
          <div style={{ color: '#94a3b8', fontSize: '0.9rem' }}>Querying the historian…</div>
        </div>
      )}

      {!running && result && result.error && (
        <div className="card">
          <div style={{ color: '#ef4444', fontSize: '0.9rem' }}>The query failed: {result.error}</div>
        </div>
      )}

      {!running && result && !result.error && !result.found && (
        <div className="card">
          <div style={{ color: '#eab308', fontSize: '0.95rem', fontWeight: 'bold' }}>
            No warranty metrics are recorded for container &apos;{containerId.trim()}&apos;.
          </div>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem', marginTop: '8px', marginBottom: 0 }}>
            The platform computes no degradation or warranty metrics on its own. A container
            appears here only once a recorder has written its throughput, cycle count, temperature
            history and state of health to the historian.
          </p>
        </div>
      )}

      {!running && metrics && (
        <>
          <div className="grid-cards">
            <div className="card">
              <div className="card-title">Total Energy Throughput</div>
              <div className="card-value">
                {measured(
                  metrics.total_energy_throughput_wh === null
                    ? null
                    : metrics.total_energy_throughput_wh / 1e6,
                  'MWh',
                )}
              </div>
              <div className="card-note">Lifetime Discharge</div>
            </div>

            <div className="card">
              <div className="card-title">Equivalent Full Cycles</div>
              <div className="card-value">{measured(metrics.equivalent_full_cycles, 'EFC', 2)}</div>
              <div className="card-note">Calculated Cycles</div>
            </div>

            <div className="card">
              <div className="card-title">Current State of Health</div>
              <div
                className="card-value"
                style={{ color: metrics.current_soh_pct === null ? '#94a3b8' : '#22c55e' }}
              >
                {measured(metrics.current_soh_pct, '% SOH', 1)}
              </div>
              <div className="card-note">Warranty Baseline</div>
            </div>

            <div className="card">
              <div className="card-title">Warranty Verdict</div>
              <div className="card-value" style={{ color: verdict.colour }}>
                {verdict.label}
              </div>
              <div className="card-note">Warranty Threshold {measured(metrics.warranty_threshold_pct, '%', 0)}</div>
            </div>
          </div>

          <div className="card">
            <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Operating History</h3>
            <div style={{ color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.8 }}>
              <div>
                <strong>Maximum Temperature Recorded:</strong>{' '}
                {measured(metrics.max_temperature_recorded_c, '°C', 1)}
              </div>
              <div>
                <strong>Time Above 45 °C:</strong>{' '}
                {measured(metrics.time_above_45c_seconds, 's', 1)}
              </div>
              <div>
                <strong>Projected State of Health:</strong>{' '}
                <span>{measured(metrics.projected_soh_pct, '% SOH', 1)}</span>
                {metrics.projection_horizon_years !== null && (
                  <span> over {metrics.projection_horizon_years} years</span>
                )}
              </div>
              <div>
                <strong>Last Updated (simulation time):</strong>{' '}
                {formatSimulationTime(metrics.updated_at_ns)}
              </div>
              <div>
                <strong>Simulation Run:</strong> {metrics.simulation_run_id}
              </div>
            </div>
            <p style={{ color: '#94a3b8', fontSize: '0.85rem', marginTop: '10px', marginBottom: 0 }}>
              {verdict.note}
            </p>
            {metrics.illustrative && (
              <p style={{ color: '#eab308', fontSize: '0.85rem', marginTop: '8px', marginBottom: 0 }}>
                The degradation model behind the verdict and the projection is illustrative: its
                constants have not been validated against any manufacturer document. The figures
                are indicative, not a warranty calculation.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
};
