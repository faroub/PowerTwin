/**
 * A mock platform for the end-to-end suite.
 *
 * The end-to-end specs drive the built HMI in a real browser. They must not
 * talk to a running backend, and above all they must not be able to: a test
 * that accidentally reached a live system would be an outward-facing action
 * against an installation nobody authorised, which is exactly what the
 * platform's safety rules forbid.
 *
 * The mock therefore works in two layers:
 *
 * 1. Every request to `/api/v1/**` is answered from this file. A path that
 *    the mock does not know is **aborted and recorded as a failure**, so a
 *    spec can never quietly depend on an endpoint nobody modelled.
 * 2. Every request to a host other than the local preview server is
 *    aborted, and the host is recorded. A spec that asserted the mock was
 *    hermetic can then prove it: the list of blocked hosts has to be empty.
 *
 * Nothing here opens a socket. The mock lives entirely inside the browser's
 * request interception.
 */

import type { Page, Route } from '@playwright/test';

/** The host the preview server is bound to. Nothing else may be contacted. */
export const PREVIEW_HOST = '127.0.0.1';

/** One request the page made to the platform API. */
export interface RecordedApiRequest {
  method: string;
  path: string;
  authorization: string | undefined;
  body: unknown;
}

/** The state the mock keeps while a spec runs. */
export interface MockPlatform {
  /** Every request the page made to the platform API, in order. */
  readonly requests: RecordedApiRequest[];
  /** API paths the mock did not model. A spec must never produce one. */
  readonly unknownPaths: string[];
  /** Hosts outside the preview server that the page tried to reach. */
  readonly blockedHosts: string[];
  /** The engine state the mock reports. A control action changes it. */
  engineState: string;
  /** The wall-clock pacing factor in force. SET_SPEED changes it. */
  speedFactor: number;
}

/** The token the mock issues. It is a fixture, not a credential. */
export const MOCK_TOKEN = 'e2e-mock-access-token';

const PERMISSIONS = ['READ_TELEMETRY', 'READ_CONFIG', 'MODIFY_SIMULATION'];

/** The pacing bounds the backend enforces. The mock refuses the same ones. */
export const MIN_SPEED_FACTOR = 0;
export const MAX_SPEED_FACTOR = 100;

function systemInfo(engineState: string, speedFactor: number) {
  return {
    project_name: 'PowerTwin BESS Platform',
    version: '1.0.0',
    environment: 'e2e',
    safety: {
      application_mode: 'SIMULATION ONLY',
      simulation_only: true,
      hardware_integration_enabled: false,
      allow_external_modbus_writes: false,
      automatic_device_discovery_enabled: false,
      safety_status: 'ACTIVE_SIMULATION_GUARDRAILS_ENFORCED',
    },
    engine: {
      status: engineState,
      mode: 'REALTIME',
      current_tick: 4242,
      is_running: engineState === 'RUNNING',
      speed_factor: speedFactor,
      message: 'The simulation engine is running.',
    },
  };
}

function plantOverview() {
  return {
    plant_name: 'Reference Plant',
    active_power_mw: 4.25,
    reactive_power_mvar: 1.5,
    avail_charge_mw: 5.0,
    avail_discharge_mw: 5.0,
    total_energy_mwh: 12.75,
    average_soc_pct: 63.5,
    grid_frequency_hz: 50.0,
    poi_voltage_kv: 33.0,
    active_alarms_count: 0,
    equipment_availability_pct: 100,
    simulation_state: 'RUNNING',
    simulation_time_str: '00:01:23.450.000',
    wall_clock_time_str: '09:15:42',
  };
}

export interface Reply {
  status: number;
  body: unknown;
}

/** Options that let a spec bend the mock for one specific scenario. */
export interface MockPlatformOptions {
  /**
   * Replace the answer for a path, keyed by path only. Used to model a
   * backend that is present but not ready, or one that refuses an action.
   */
  overrides?: Record<string, Reply>;
}

/**
 * Answer one platform request.
 *
 * Returns `undefined` for a path the mock does not model, which the caller
 * turns into an aborted request and a recorded failure.
 */
function replyTo(
  method: string,
  path: string,
  body: unknown,
  state: MockPlatform,
  overrides: Record<string, Reply>,
): Reply | undefined {
  const override = overrides[path];
  if (override) {
    return override;
  }

  if (method === 'POST' && path === '/api/v1/auth/login') {
    return {
      status: 200,
      body: {
        access_token: MOCK_TOKEN,
        token_type: 'bearer',
        username: 'engineer',
        role: 'ENGINEER',
        permissions: PERMISSIONS,
      },
    };
  }

  if (method === 'GET' && path === '/api/v1/auth/me') {
    return {
      status: 200,
      body: { username: 'engineer', role: 'ENGINEER', permissions: PERMISSIONS },
    };
  }

  if (method === 'GET' && path === '/api/v1/info') {
    return { status: 200, body: systemInfo(state.engineState, state.speedFactor) };
  }

  if (method === 'GET' && path === '/api/v1/overview') {
    return { status: 200, body: plantOverview() };
  }

  if (method === 'POST' && path === '/api/v1/simulation/control') {
    const action = (body as { action?: string } | null)?.action;
    if (action === 'START') {
      state.engineState = 'RUNNING';
    } else if (action === 'PAUSE') {
      state.engineState = 'PAUSED';
    } else if (action === 'STOP') {
      state.engineState = 'STOPPED';
    } else if (action === 'RESET') {
      state.engineState = 'RUNNING';
    } else if (action === 'SET_SPEED') {
      const factor = (body as { speed_factor?: number } | null)?.speed_factor;
      // The mock refuses the same factors the backend refuses, so a spec
      // cannot pass against a mock that accepts what the platform rejects.
      if (
        typeof factor !== 'number' ||
        !Number.isFinite(factor) ||
        factor < MIN_SPEED_FACTOR ||
        factor > MAX_SPEED_FACTOR
      ) {
        return {
          status: 400,
          body: {
            detail: `SET_SPEED action requires a 'speed_factor' between ${MIN_SPEED_FACTOR} and ${MAX_SPEED_FACTOR}; ${factor} was received.`,
          },
        };
      }
      state.speedFactor = factor;
    }
    return {
      status: 200,
      body: {
        status: 'SUCCESS',
        engine_state: state.engineState,
        message: `The action ${action ?? 'unknown'} was executed.`,
      },
    };
  }

  return undefined;
}

/**
 * Install the mock platform on a page.
 *
 * The returned handle records what the page asked for, so that a spec can
 * assert on the requests it made rather than only on what it saw.
 */
export async function installMockPlatform(
  page: Page,
  options: MockPlatformOptions = {},
): Promise<MockPlatform> {
  const state: MockPlatform = {
    requests: [],
    unknownPaths: [],
    blockedHosts: [],
    engineState: 'RUNNING',
    speedFactor: 1.0,
  };
  const overrides = options.overrides ?? {};

  await page.route('**/api/v1/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    let parsed: unknown = undefined;
    const raw = request.postData();
    if (raw) {
      try {
        parsed = JSON.parse(raw);
      } catch {
        parsed = raw;
      }
    }

    state.requests.push({
      method: request.method(),
      path: url.pathname,
      authorization: request.headers()['authorization'],
      body: parsed,
    });

    const reply = replyTo(request.method(), url.pathname, parsed, state, overrides);
    if (reply === undefined) {
      state.unknownPaths.push(url.pathname);
      await route.abort('failed');
      return;
    }

    await route.fulfill({
      status: reply.status,
      contentType: 'application/json',
      body: JSON.stringify(reply.body),
    });
  });

  // The hermetic guard. It is registered last, so it is consulted first: a
  // request that is not to the local preview server never leaves the browser.
  await page.route('**/*', async (route: Route) => {
    const hostname = new URL(route.request().url()).hostname;
    if (hostname === PREVIEW_HOST || hostname === 'localhost') {
      await route.fallback();
      return;
    }
    state.blockedHosts.push(hostname);
    await route.abort('blockedbyclient');
  });

  return state;
}

/** Log the operator in through the HMI's own login form. */
export async function logIn(page: Page): Promise<void> {
  await page.getByPlaceholder('Username (observer, engineer, admin)').fill('engineer');
  await page.getByPlaceholder('Password').fill('e2e-password');
  await page.getByRole('button', { name: 'Consent & Login' }).click();
  await page.getByRole('heading', { level: 1, name: 'Plant Overview' }).waitFor();
}

/** Open a view of the HMI through the sidebar. */
export async function openView(page: Page, label: string): Promise<void> {
  await page.getByText(label, { exact: true }).click();
}
