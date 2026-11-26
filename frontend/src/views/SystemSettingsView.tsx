import React, { useEffect, useState } from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import { fetchSystemHealth, SafetyReport, SystemInfo } from '../services/api';

/**
 * One safety invariant, and how the platform reports it.
 *
 * The invariant is read from the running platform rather than printed from a
 * constant on the screen: the values the backend reports are the ones the
 * safety guardrails enforce, and a screen that asserts them on its own is a
 * screen that can disagree with the platform without anyone noticing.
 */
interface Invariant {
  label: string;
  /** The field of the safety report that carries the invariant. */
  field: keyof SafetyReport;
}

/**
 * The invariants, in the order the platform documents them.
 *
 * A field whose value is a boolean is rendered as ENABLED or DISABLED. The
 * mode is a string and is rendered as the platform reports it.
 */
const INVARIANTS: Invariant[] = [
  // The label names the mode rather than the guardrail, because the field is
  // true when the platform is *in* simulation-only mode. A row called
  // "Simulation Only: DISABLED" would read as "simulation is off" and as
  // "the simulation-only guardrail is off" at the same time.
  { label: 'Simulation-Only Mode', field: 'simulation_only' },
  { label: 'Hardware Integration', field: 'hardware_integration_enabled' },
  { label: 'External Modbus Writes', field: 'allow_external_modbus_writes' },
  { label: 'Automatic Device Discovery', field: 'automatic_device_discovery_enabled' },
];

export const SystemSettingsView: React.FC = () => {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [reachable, setReachable] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    const read = async () => {
      const health = await fetchSystemHealth();
      if (!mounted) {
        return;
      }
      setInfo(health.data ?? null);
      setReachable(health.healthy && health.data !== undefined);
    };
    read();
    return () => {
      mounted = false;
    };
  }, []);

  const safety = info?.safety ?? null;

  /**
   * Render one invariant.
   *
   * When the platform did not answer, the invariant reads UNVERIFIED. It is
   * not shown as DISABLED: the platform's code enforces the invariant either
   * way, but the screen has no evidence of the running state, and claiming
   * one it did not read would be the same error as printing a constant.
   */
  const renderInvariant = (invariant: Invariant) => {
    if (!reachable || safety === null) {
      return (
        <div>
          <strong>{invariant.label}:</strong>{' '}
          <span style={{ color: '#eab308' }}>UNVERIFIED</span>
        </div>
      );
    }
    const value = safety[invariant.field];
    if (typeof value !== 'boolean') {
      return (
        <div>
          <strong>{invariant.label}:</strong> {String(value)}
        </div>
      );
    }
    return (
      <div>
        <strong>{invariant.label}:</strong>{' '}
        <span style={{ color: value ? '#ef4444' : '#22c55e' }}>
          {value ? 'ENABLED' : 'DISABLED'}
        </span>
      </div>
    );
  };

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">System Settings</h1>
        <p className="view-subtitle">Application Configuration and Safety Invariants</p>
      </div>

      <SimulatedDataNotice detail="The configuration and safety invariants of the running platform, as the platform reports them." />

      <div className="card" style={{ marginBottom: '16px' }}>
        <h3 style={{ color: '#ef4444', marginBottom: '12px' }}>Non-Negotiable Safety Invariants</h3>
        <div style={{ color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.6 }}>
          {safety !== null && (
            <div>
              <strong>Application Mode:</strong> {safety.application_mode}
            </div>
          )}
          {INVARIANTS.map((invariant) => (
            <React.Fragment key={invariant.field}>{renderInvariant(invariant)}</React.Fragment>
          ))}
        </div>
        {!reachable && (
          <p style={{ color: '#eab308', fontSize: '0.85rem', marginTop: '12px', marginBottom: 0 }}>
            The platform did not answer, so the invariants above are not verified. The safety
            guardrails are enforced by the platform code and are not switched off by an
            unreachable screen.
          </p>
        )}
      </div>

      <div className="card">
        <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Platform</h3>
        <div style={{ color: '#94a3b8', fontSize: '0.9rem', lineHeight: 1.8 }}>
          <div>
            <strong>Project:</strong> {info?.project_name ?? 'UNAVAILABLE'}
          </div>
          <div>
            <strong>Version:</strong> {info?.version ?? 'UNAVAILABLE'}
          </div>
          <div>
            <strong>Environment:</strong> {info?.environment ?? 'UNAVAILABLE'}
          </div>
          <div>
            <strong>Safety Status:</strong> {safety?.safety_status ?? 'UNAVAILABLE'}
          </div>
        </div>
      </div>
    </div>
  );
};
