/**
 * A controllable `fetch` double for the component suite.
 *
 * The HMI talks to the backend through the global `fetch`. The suite replaces
 * that global with a table of route handlers, so that a test states exactly
 * which endpoints the component under test is allowed to touch.
 *
 * A request that matches no route is an **error**, not an empty response. That
 * is deliberate: a silent fallback would let a component call an endpoint the
 * test did not anticipate, and the test would still pass. Failing loudly keeps
 * the mock honest and keeps the suite from accidentally asserting behaviour
 * that depends on an unstubbed call.
 */

import { vi } from 'vitest';

/** The subset of `Response` that the HMI actually reads. */
export interface MockResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

/** A response carrying a JSON body. */
export function jsonResponse(body: unknown, status = 200): MockResponse {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

/** A response that fails at the transport level. */
export function networkFailure(message = 'the connection was refused'): MockResponse {
  throw new Error(message);
}

/** Handles one route; may be asynchronous. */
export type RouteHandler = (
  url: string,
  init?: RequestInit,
) => MockResponse | Promise<MockResponse>;

/** One recorded call. */
export interface RecordedCall {
  url: string;
  method: string;
  init?: RequestInit;
}

/** The handle returned by {@link installFetchMock}. */
export interface FetchMock {
  /** Every call the component made, in order. */
  readonly calls: RecordedCall[];
  /** The calls that targeted one path fragment. */
  callsTo(pathFragment: string): RecordedCall[];
}

function describeUrl(input: unknown): string {
  if (typeof input === 'string') {
    return input;
  }
  if (input instanceof URL) {
    return input.toString();
  }
  if (input && typeof input === 'object' && 'url' in input) {
    return String((input as { url: unknown }).url);
  }
  return String(input);
}

/**
 * Replace the global `fetch` with a route table.
 *
 * The keys are matched as path fragments against the requested URL, so
 * `/api/v1/overview` matches `http://localhost/api/v1/overview`.
 */
export function installFetchMock(routes: Record<string, RouteHandler>): FetchMock {
  const calls: RecordedCall[] = [];

  const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
    const url = describeUrl(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, init });

    const matched = Object.keys(routes).find((fragment) => url.includes(fragment));
    if (matched === undefined) {
      throw new Error(`The component made an unexpected request to ${url}`);
    }
    return routes[matched](url, init);
  });

  vi.stubGlobal('fetch', fetchMock);

  return {
    calls,
    callsTo(pathFragment: string): RecordedCall[] {
      return calls.filter((call) => call.url.includes(pathFragment));
    },
  };
}

/**
 * Read the bearer token from a recorded call, if it carries one.
 *
 * The HMI builds its headers as a plain object, so the cast is exact rather
 * than a convenience.
 */
export function bearerTokenOf(call: RecordedCall | undefined): string | undefined {
  const headers = call?.init?.headers as Record<string, string> | undefined;
  const header = headers?.['Authorization'];
  if (!header) {
    return undefined;
  }
  return header.startsWith('Bearer ') ? header.slice('Bearer '.length) : undefined;
}

/** Read the JSON body a recorded call sent. */
export function bodyOf(call: RecordedCall | undefined): Record<string, unknown> | undefined {
  const body = call?.init?.body;
  if (typeof body !== 'string') {
    return undefined;
  }
  try {
    return JSON.parse(body) as Record<string, unknown>;
  } catch {
    return undefined;
  }
}
