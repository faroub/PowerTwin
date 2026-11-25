import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { usePlantTelemetry } from '../hooks';
import { platformSession } from '../api';

import { CONNECTED_TELEMETRY, DISCONNECTED_TELEMETRY } from '../../test/fixtures';
import { bearerTokenOf, installFetchMock, jsonResponse } from '../../test/fetchMock';

/** A polling interval long enough that the suite never sees a second poll. */
const NEVER_REPOLL = 60_000;

describe('Plant Telemetry Hook', () => {
  it('reports that it is loading before the first answer arrives', () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });

    const { result } = renderHook(() => usePlantTelemetry(NEVER_REPOLL));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('exposes the telemetry bundle the backend reports', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });

    const { result } = renderHook(() => usePlantTelemetry(NEVER_REPOLL));

    await waitFor(() => expect(result.current.data).not.toBeNull());

    expect(result.current.data?.plant_name).toBe('Reference Plant');
    expect(result.current.data?.active_power_mw).toBe(4.25);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.isConnected).toBe(true);
  });

  it('reports the plant as disconnected when the engine is not connected', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(DISCONNECTED_TELEMETRY),
    });

    const { result } = renderHook(() => usePlantTelemetry(NEVER_REPOLL));

    await waitFor(() => expect(result.current.data).not.toBeNull());

    expect(result.current.isConnected).toBe(false);
  });

  it('attaches the session token to the telemetry request', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });
    platformSession.setAuthenticated(
      { username: 'engineer', role: 'ENGINEER', permissions: new Set() },
      'telemetry-token',
    );

    const { result } = renderHook(() => usePlantTelemetry(NEVER_REPOLL));
    await waitFor(() => expect(result.current.data).not.toBeNull());

    expect(bearerTokenOf(mock.callsTo('/api/v1/overview')[0])).toBe('telemetry-token');
  });

  it('reports the status code when the backend answers with an error', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse({ detail: 'not authorised' }, 403),
    });

    const { result } = renderHook(() => usePlantTelemetry(NEVER_REPOLL));

    await waitFor(() => expect(result.current.error).not.toBeNull());

    expect(result.current.error).toBe('Overview request failed with status 403');
    expect(result.current.data).toBeNull();
    expect(result.current.isConnected).toBe(false);
  });

  it('reports a network error when the backend cannot be reached', async () => {
    installFetchMock({
      '/api/v1/overview': () => {
        throw new Error('the connection was refused');
      },
    });

    const { result } = renderHook(() => usePlantTelemetry(NEVER_REPOLL));

    await waitFor(() => expect(result.current.error).not.toBeNull());

    expect(result.current.error).toBe('Network error connecting to backend API.');
    expect(result.current.isConnected).toBe(false);
  });

  it('polls again on the configured interval', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });

    const { result } = renderHook(() => usePlantTelemetry(20));

    await waitFor(() => expect(result.current.data).not.toBeNull());
    await waitFor(() => expect(mock.callsTo('/api/v1/overview').length).toBeGreaterThan(1));
  });

  it('stops polling once the view is unmounted', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });

    const { result, unmount } = renderHook(() => usePlantTelemetry(20));
    await waitFor(() => expect(result.current.data).not.toBeNull());

    unmount();
    const callsAtUnmount = mock.callsTo('/api/v1/overview').length;

    await new Promise((resolve) => setTimeout(resolve, 120));

    expect(mock.callsTo('/api/v1/overview').length).toBe(callsAtUnmount);
  });
});
