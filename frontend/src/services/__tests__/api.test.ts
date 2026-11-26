import { beforeEach, describe, expect, it } from 'vitest';

import {
  dispatchSimulationControl,
  fetchHistorianAlarms,
  fetchHistorianCommands,
  fetchHistorianTelemetry,
  fetchPlantOverview,
  fetchSystemHealth,
  fetchUserDetails,
  fetchWarrantyMetrics,
  login,
  logout,
  platformSession,
} from '../api';
import type { UserSession } from '../auth';

import {
  CONNECTED_TELEMETRY,
  HEALTHY_SYSTEM_INFO,
  TOKEN_RESPONSE,
  USER_DETAILS,
} from '../../test/fixtures';
import { bearerTokenOf, bodyOf, installFetchMock, jsonResponse } from '../../test/fetchMock';

describe('Platform Session Bridging', () => {
  it('remains unauthenticated until a login completes', () => {
    expect(platformSession.isAuthenticated).toBe(false);
    expect(platformSession.token).toBe(null);
    expect(platformSession.user).toBe(null);
  });

  it('records a user session and exposes the token without persisting it', () => {
    const mockSession: UserSession = {
      username: 'engineer',
      role: 'engineer',
      permissions: new Set(['READ_TELEMETRY']),
    };
    platformSession.setAuthenticated(mockSession, 'test-token');
    expect(platformSession.isAuthenticated).toBe(true);
    expect(platformSession.token).toBe('test-token');
    expect(platformSession.user).toEqual(mockSession);

    platformSession.clear();
    expect(platformSession.isAuthenticated).toBe(false);
    expect(platformSession.token).toBe(null);
    expect(platformSession.user).toBe(null);
  });

  it('never writes the session token to any client-side storage', () => {
    platformSession.setAuthenticated(
      { username: 'engineer', role: 'ENGINEER', permissions: new Set() },
      'a-token-that-must-not-be-persisted',
    );

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe('');
  });
});

describe('System Health', () => {
  it('reports the platform as healthy and returns the reported information', async () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });

    const result = await fetchSystemHealth();

    expect(result.healthy).toBe(true);
    expect(result.data?.safety.application_mode).toBe('SIMULATION ONLY');
    expect(result.data?.safety.hardware_integration_enabled).toBe(false);
  });

  it('reports the platform as unhealthy when the backend answers with an error', async () => {
    installFetchMock({
      '/api/v1/info': () => jsonResponse({ detail: 'not ready' }, 503),
    });

    const result = await fetchSystemHealth();

    expect(result.healthy).toBe(false);
    expect(result.data).toBeUndefined();
  });

  it('reports the platform as unhealthy when the backend cannot be reached', async () => {
    installFetchMock({
      '/api/v1/info': () => {
        throw new Error('the connection was refused');
      },
    });

    const result = await fetchSystemHealth();

    expect(result.healthy).toBe(false);
  });

  it('attaches the session token to the health request', async () => {
    const mock = installFetchMock({
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    });
    platformSession.setAuthenticated(
      { username: 'engineer', role: 'ENGINEER', permissions: new Set() },
      'health-token',
    );

    await fetchSystemHealth();

    expect(bearerTokenOf(mock.callsTo('/api/v1/info')[0])).toBe('health-token');
  });
});

describe('Plant Overview', () => {
  it('returns the telemetry bundle the backend reports', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });

    const result = await fetchPlantOverview();

    expect(result?.plant_name).toBe('Reference Plant');
    expect(result?.active_power_mw).toBe(4.25);
  });

  it('returns nothing when the backend answers with an error', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse({ detail: 'unauthorised' }, 401),
    });

    expect(await fetchPlantOverview()).toBeNull();
  });

  it('returns nothing when the backend cannot be reached', async () => {
    installFetchMock({
      '/api/v1/overview': () => {
        throw new Error('the connection was refused');
      },
    });

    expect(await fetchPlantOverview()).toBeNull();
  });
});

describe('Simulation Control Dispatch', () => {
  beforeEach(() => {
    platformSession.setAuthenticated(
      { username: 'engineer', role: 'ENGINEER', permissions: new Set() },
      'dispatch-token',
    );
  });

  it('reports a successful action and the resulting engine state', async () => {
    installFetchMock({
      '/api/v1/simulation/control': () =>
        jsonResponse({ status: 'SUCCESS', engine_state: 'PAUSED', message: 'The engine is paused.' }),
    });

    const result = await dispatchSimulationControl('PAUSE');

    expect(result.success).toBe(true);
    expect(result.status).toBe('SUCCESS');
    expect(result.engine_state).toBe('PAUSED');
    expect(result.message).toBe('The engine is paused.');
  });

  it('sends the action together with the session token', async () => {
    const mock = installFetchMock({
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });

    await dispatchSimulationControl('STEP', { steps: 1 });

    const call = mock.callsTo('/api/v1/simulation/control')[0];
    expect(call.method).toBe('POST');
    expect(bearerTokenOf(call)).toBe('dispatch-token');
    expect(bodyOf(call)).toEqual({ action: 'STEP', steps: 1 });
  });

  it('reports a disconnected engine rather than a failure when the engine is absent', async () => {
    installFetchMock({
      '/api/v1/simulation/control': () =>
        jsonResponse({ detail: { message: 'The engine is not connected.' } }, 503),
    });

    const result = await dispatchSimulationControl('PAUSE');

    expect(result.success).toBe(false);
    expect(result.status).toBe('NOT_CONNECTED');
    expect(result.message).toBe('The engine is not connected.');
  });

  it('reports an authorisation failure without attempting the action', async () => {
    installFetchMock({
      '/api/v1/simulation/control': () => jsonResponse({ detail: 'forbidden' }, 403),
    });

    const result = await dispatchSimulationControl('PAUSE');

    expect(result.success).toBe(false);
    expect(result.status).toBe('UNAUTHORIZED');
    expect(result.message).toContain('permission');
  });

  it('reports a rejected action', async () => {
    installFetchMock({
      '/api/v1/simulation/control': () =>
        jsonResponse({ detail: { message: 'The action was rejected.' } }, 500),
    });

    const result = await dispatchSimulationControl('RESET');

    expect(result.success).toBe(false);
    expect(result.status).toBe('FAILED');
    expect(result.message).toBe('The action was rejected.');
  });

  it('reports a disconnection when the backend cannot be reached', async () => {
    installFetchMock({
      '/api/v1/simulation/control': () => {
        throw new Error('the connection was refused');
      },
    });

    const result = await dispatchSimulationControl('PAUSE');

    expect(result.success).toBe(false);
    expect(result.status).toBe('DISCONNECTED');
    expect(result.message).toContain('Network error');
  });
});

describe('Login', () => {
  it('returns the token the backend issued', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
    });

    const result = await login({ username: 'engineer', password: 'secret' });

    expect(result?.access_token).toBe('test-access-token');
    expect(result?.role).toBe('ENGINEER');
  });

  it('forwards the credentials to the backend and keeps them out of the session', async () => {
    const mock = installFetchMock({
      '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
    });

    await login({ username: 'engineer', password: 'secret' });

    const call = mock.callsTo('/api/v1/auth/login')[0];
    expect(call.method).toBe('POST');
    expect(bodyOf(call)).toEqual({ username: 'engineer', password: 'secret' });
    expect(platformSession.isAuthenticated).toBe(false);
  });

  it('returns nothing when the credentials are rejected', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse({ detail: 'invalid credentials' }, 401),
    });

    expect(await login({ username: 'engineer', password: 'wrong' })).toBeNull();
  });

  it('returns nothing when the backend cannot be reached', async () => {
    installFetchMock({
      '/api/v1/auth/login': () => {
        throw new Error('the connection was refused');
      },
    });

    expect(await login({ username: 'engineer', password: 'secret' })).toBeNull();
  });
});

describe('Session Details', () => {
  it('builds the session from the permissions the backend reports', async () => {
    installFetchMock({
      '/api/v1/auth/me': () => jsonResponse(USER_DETAILS),
    });

    const user = await fetchUserDetails('test-access-token');

    expect(user?.username).toBe('engineer');
    expect(user?.role).toBe('ENGINEER');
    expect(user?.permissions.has('MODIFY_SIMULATION')).toBe(true);
    expect(user?.permissions.has('ADMINISTER_SYSTEM')).toBe(false);
  });

  it('falls back to the role table when the backend reports no permissions', async () => {
    installFetchMock({
      '/api/v1/auth/me': () => jsonResponse({ username: 'observer', role: 'OBSERVER', permissions: [] }),
    });

    const user = await fetchUserDetails('test-access-token');

    expect(user?.permissions.has('READ_TELEMETRY')).toBe(true);
    expect(user?.permissions.has('MODIFY_SIMULATION')).toBe(false);
  });

  it('returns nothing when the session cannot be verified', async () => {
    installFetchMock({
      '/api/v1/auth/me': () => jsonResponse({ detail: 'invalid token' }, 401),
    });

    expect(await fetchUserDetails('stale-token')).toBeNull();
  });

  it('returns nothing when the backend cannot be reached', async () => {
    installFetchMock({
      '/api/v1/auth/me': () => {
        throw new Error('the connection was refused');
      },
    });

    expect(await fetchUserDetails('test-access-token')).toBeNull();
  });
});

describe('Logout', () => {
  it('clears the in-memory session', () => {
    platformSession.setAuthenticated(
      { username: 'engineer', role: 'ENGINEER', permissions: new Set() },
      'a-token',
    );

    logout();

    expect(platformSession.isAuthenticated).toBe(false);
    expect(platformSession.token).toBe(null);
    expect(platformSession.user).toBe(null);
  });
});

describe('Historian Queries', () => {
  it('returns the rows the historian holds', async () => {
    installFetchMock({
      '/api/v1/historian/telemetry': () =>
        jsonResponse({
          count: 1,
          records: [
            {
              timestamp_ns: 1,
              source_timestamp_ns: 1,
              tag_id: 'dc_voltage_v',
              equipment_id: 'CONTAINER_01',
              value: 812.4,
              unit: 'V',
              quality: 'GOOD',
              source_type: 'SIMULATED',
              simulation_run_id: 'RUN_01',
            },
          ],
        }),
    });

    const result = await fetchHistorianTelemetry({ equipment_id: 'CONTAINER_01' });

    expect(result.ok).toBe(true);
    expect(result.records).toHaveLength(1);
    expect(result.records[0].equipment_id).toBe('CONTAINER_01');
  });

  it('leaves an empty filter out of the query', async () => {
    const mock = installFetchMock({
      '/api/v1/historian/telemetry': () => jsonResponse({ count: 0, records: [] }),
    });

    await fetchHistorianTelemetry({ equipment_id: '', tag_id: '', limit: 10 });

    // An empty filter sent as a query parameter would narrow the query to
    // equipment whose identifier is the empty string and return nothing.
    expect(mock.callsTo('/api/v1/historian/telemetry')[0].url).not.toContain('equipment_id=');
    expect(mock.callsTo('/api/v1/historian/telemetry')[0].url).toContain('limit=10');
  });

  it('reports a failed command query', async () => {
    installFetchMock({
      '/api/v1/historian/commands': () => jsonResponse({ detail: 'the store is unavailable' }, 503),
    });

    const result = await fetchHistorianCommands();

    expect(result.ok).toBe(false);
    expect(result.records).toEqual([]);
    expect(result.error).toBe('the store is unavailable');
  });

  it('reports a failed alarm query', async () => {
    installFetchMock({
      '/api/v1/historian/alarms': () => jsonResponse({ detail: 'the store is unavailable' }, 503),
    });

    const result = await fetchHistorianAlarms();

    expect(result.ok).toBe(false);
    expect(result.records).toEqual([]);
    expect(result.error).toBe('the store is unavailable');
  });

  it('reports the status code when the failure carries no explanation', async () => {
    installFetchMock({
      '/api/v1/historian/telemetry': () => ({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('the body is not JSON');
        },
      }),
    });

    const result = await fetchHistorianTelemetry();

    expect(result.ok).toBe(false);
    expect(result.error).toContain('500');
  });

  it('reports a network failure as a failed query', async () => {
    installFetchMock({
      '/api/v1/historian/telemetry': () => {
        throw new Error('the connection was refused');
      },
    });

    const result = await fetchHistorianTelemetry();

    expect(result.ok).toBe(false);
    expect(result.status).toBe(0);
    expect(result.error).toBe('Network error connecting to the backend API.');
  });

  it('reports a warranty container with no record as not found rather than failed', async () => {
    installFetchMock({
      '/api/v1/historian/warranty/CONTAINER_01': () =>
        jsonResponse({ detail: "No warranty metrics recorded for container 'CONTAINER_01'." }, 404),
    });

    const result = await fetchWarrantyMetrics('CONTAINER_01');

    // A missing record is a true statement about the platform's state, not
    // an error the operator has to act on.
    expect(result.found).toBe(false);
    expect(result.error).toBeNull();
    expect(result.status).toBe(404);
  });

  it('reports a failed warranty query as a failure', async () => {
    installFetchMock({
      '/api/v1/historian/warranty/CONTAINER_01': () =>
        jsonResponse({ detail: 'the store is unavailable' }, 503),
    });

    const result = await fetchWarrantyMetrics('CONTAINER_01');

    expect(result.found).toBe(false);
    expect(result.error).toBe('the store is unavailable');
  });
});
