import React, { useState } from 'react';

import { SimulatedDataNotice } from '../components/SimulatedDataNotice';
import {
  fetchHistorianAlarms,
  fetchHistorianCommands,
  fetchHistorianTelemetry,
  HistorianAlarmRecord,
  HistorianCommandRecord,
  HistorianTelemetryRecord,
} from '../services/api';

/**
 * The number of rows a query asks for when the operator does not choose one.
 *
 * The backend caps every query, and a screen that returns thousands of rows
 * is a screen nobody reads. The cap is the operator's to raise.
 */
const DEFAULT_LIMIT = 100;

/** The state of one of the three historian queries. */
interface QueryState<T> {
  /** The rows the backend returned; empty until a query has run. */
  records: T[];
  /** Why the query failed, when it failed. */
  error: string | null;
  /** True while the query is in flight. */
  running: boolean;
  /** True once a query has run, whether it returned rows or not. */
  attempted: boolean;
}

const EMPTY_QUERY: QueryState<never> = {
  records: [],
  error: null,
  running: false,
  attempted: false,
};

/** The columns one result table shows. */
interface Column<T> {
  header: string;
  render: (record: T) => string;
}

/**
 * Render the rows of one historian query.
 *
 * An empty result and a failed result are shown differently on purpose. "No
 * rows" means the store holds nothing for that filter; "the query failed"
 * means the platform did not answer, and the operator has to know which of
 * the two they are looking at.
 */
const QueryTable: React.FC<{
  title: string;
  columns: Column<unknown>[];
  records: unknown[];
  error: string | null;
  running: boolean;
  attempted: boolean;
  emptyLabel: string;
}> = ({ title, columns, records, error, running, attempted, emptyLabel }) => {
  const rows = records as Record<string, unknown>[];

  return (
    <div className="card" style={{ marginBottom: '16px' }}>
      <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>{title}</h3>
      {running && <div style={{ color: '#94a3b8', fontSize: '0.9rem' }}>Querying the historian…</div>}
      {!running && error && (
        <div style={{ color: '#ef4444', fontSize: '0.9rem' }}>The query failed: {error}</div>
      )}
      {!running && !error && !attempted && (
        <div style={{ color: '#94a3b8', fontSize: '0.9rem' }}>
          No query has been run yet.
        </div>
      )}
      {!running && !error && attempted && rows.length === 0 && (
        <div style={{ color: '#94a3b8', fontSize: '0.9rem' }}>{emptyLabel}</div>
      )}
      {!running && !error && rows.length > 0 && (
        <>
          <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '8px' }}>
            {rows.length} row{rows.length === 1 ? '' : 's'} returned.
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th
                      key={column.header}
                      style={{
                        textAlign: 'left',
                        padding: '6px 10px',
                        color: '#94a3b8',
                        borderBottom: '1px solid #334155',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {column.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((record, index) => (
                  <tr key={index}>
                    {columns.map((column) => (
                      <td
                        key={column.header}
                        style={{
                          padding: '6px 10px',
                          borderBottom: '1px solid #1e293b',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {column.render(record)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
};

const TELEMETRY_COLUMNS: Column<HistorianTelemetryRecord>[] = [
  { header: 'Time (ns)', render: (record) => String(record.timestamp_ns) },
  { header: 'Equipment', render: (record) => record.equipment_id },
  { header: 'Tag', render: (record) => record.tag_id },
  { header: 'Value', render: (record) => `${record.value} ${record.unit}` },
  { header: 'Quality', render: (record) => record.quality },
];

const COMMAND_COLUMNS: Column<HistorianCommandRecord>[] = [
  { header: 'Time (ns)', render: (record) => String(record.timestamp_ns) },
  { header: 'Requestor', render: (record) => record.requestor },
  { header: 'Target', render: (record) => record.target_equipment_id },
  { header: 'Status', render: (record) => record.accepted_status },
  { header: 'Reason', render: (record) => record.rejection_reason },
];

const ALARM_COLUMNS: Column<HistorianAlarmRecord>[] = [
  { header: 'Time (ns)', render: (record) => String(record.timestamp_ns) },
  { header: 'Equipment', render: (record) => record.equipment_id },
  { header: 'Severity', render: (record) => record.severity },
  { header: 'Code', render: (record) => record.code },
  { header: 'Description', render: (record) => record.description },
];

export const HistorianView: React.FC = () => {
  const [equipmentId, setEquipmentId] = useState<string>('');
  const [tagId, setTagId] = useState<string>('');
  const [limit, setLimit] = useState<string>(String(DEFAULT_LIMIT));

  const [telemetry, setTelemetry] = useState<QueryState<HistorianTelemetryRecord>>(EMPTY_QUERY);
  const [commands, setCommands] = useState<QueryState<HistorianCommandRecord>>(EMPTY_QUERY);
  const [alarms, setAlarms] = useState<QueryState<HistorianAlarmRecord>>(EMPTY_QUERY);

  const inputStyle = {
    padding: '8px 10px',
    borderRadius: '6px',
    border: '1px solid #334155',
    backgroundColor: '#0f172a',
    color: '#f8fafc',
  };

  /**
   * Run the three read-only queries the screen offers.
   *
   * The queries run together because they ask the same question about the
   * same store: what the historian holds for this filter. A query that fails
   * is reported on its own panel and does not hide the panels that answered.
   */
  const runQuery = async () => {
    const parsedLimit = Number(limit);
    const rowLimit = Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : DEFAULT_LIMIT;
    const equipment = equipmentId.trim();
    const tag = tagId.trim();

    setTelemetry({ ...EMPTY_QUERY, running: true, attempted: true });
    setCommands({ ...EMPTY_QUERY, running: true, attempted: true });
    setAlarms({ ...EMPTY_QUERY, running: true, attempted: true });

    const [telemetryResult, commandResult, alarmResult] = await Promise.all([
      fetchHistorianTelemetry({
        equipment_id: equipment || undefined,
        tag_id: tag || undefined,
        limit: rowLimit,
      }),
      fetchHistorianCommands({
        target_equipment_id: equipment || undefined,
        limit: rowLimit,
      }),
      fetchHistorianAlarms({
        equipment_id: equipment || undefined,
        limit: rowLimit,
      }),
    ]);

    setTelemetry({
      records: telemetryResult.records,
      error: telemetryResult.error,
      running: false,
      attempted: true,
    });
    setCommands({
      records: commandResult.records,
      error: commandResult.error,
      running: false,
      attempted: true,
    });
    setAlarms({
      records: alarmResult.records,
      error: alarmResult.error,
      running: false,
      attempted: true,
    });
  };

  return (
    <div>
      <div className="view-header">
        <h1 className="view-title">Historian</h1>
        <p className="view-subtitle">Time-Series Telemetry Querying & Configurable Sampling</p>
      </div>

      <SimulatedDataNotice detail="Read-only queries against the historian's time-series, command audit and alarm tables. The rows shown are the ones the store holds." />

      <div className="card" style={{ marginBottom: '16px' }}>
        <h3 style={{ color: '#38bdf8', marginBottom: '12px' }}>Time-Series Query Controls</h3>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>
            <div style={{ marginBottom: '4px' }}>Equipment ID (optional)</div>
            <input
              type="text"
              value={equipmentId}
              onChange={(event) => setEquipmentId(event.target.value)}
              placeholder="CONTAINER_01"
              style={{ ...inputStyle, width: '190px' }}
            />
          </label>
          <label style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>
            <div style={{ marginBottom: '4px' }}>Tag ID (optional)</div>
            <input
              type="text"
              value={tagId}
              onChange={(event) => setTagId(event.target.value)}
              placeholder="dc_voltage_v"
              style={{ ...inputStyle, width: '190px' }}
            />
          </label>
          <label style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>
            <div style={{ marginBottom: '4px' }}>Row limit</div>
            <input
              type="number"
              min={1}
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
              style={{ ...inputStyle, width: '110px' }}
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
            RUN QUERY
          </button>
        </div>
      </div>

      <QueryTable
        title="Telemetry"
        columns={TELEMETRY_COLUMNS as Column<unknown>[]}
        records={telemetry.records}
        error={telemetry.error}
        running={telemetry.running}
        attempted={telemetry.attempted}
        emptyLabel="The historian holds no telemetry rows for this filter."
      />
      <QueryTable
        title="Command Audit Log"
        columns={COMMAND_COLUMNS as Column<unknown>[]}
        records={commands.records}
        error={commands.error}
        running={commands.running}
        attempted={commands.attempted}
        emptyLabel="The historian holds no command records for this filter."
      />
      <QueryTable
        title="Alarms & Events"
        columns={ALARM_COLUMNS as Column<unknown>[]}
        records={alarms.records}
        error={alarms.error}
        running={alarms.running}
        attempted={alarms.attempted}
        emptyLabel="The historian holds no alarm or event records for this filter."
      />
    </div>
  );
};
