import { waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  CONNECTED_TELEMETRY,
  HEALTHY_SYSTEM_INFO,
  TOKEN_RESPONSE,
  USER_DETAILS,
} from './test/fixtures';
import { installFetchMock, jsonResponse } from './test/fetchMock';

/**
 * The entry point of the HMI.
 *
 * `main.tsx` is the one file that no component test can reach, because it is
 * what mounts the application in the first place. This test mounts it into a
 * real root element and checks that the platform comes up, which is the
 * closest the unit suite gets to proving that the shipped page works.
 */
describe('Application Entry Point', () => {
  let root: HTMLElement;

  beforeEach(() => {
    root = document.createElement('div');
    root.id = 'root';
    document.body.appendChild(root);

    installFetchMock({
      '/api/v1/auth/login': () => jsonResponse(TOKEN_RESPONSE),
      '/api/v1/auth/me': () => jsonResponse(USER_DETAILS),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    });
  });

  afterEach(() => {
    root.remove();
  });

  it('mounts the HMI into the root element of the page', async () => {
    await import('./main');

    await waitFor(() => {
      expect(root.textContent).toContain('PowerTwin BESS Platform');
    });
    expect(root.textContent).toContain('Log in to the HMI session');
    expect(root.textContent).toContain('No hardware equipment is detected during login');
  });
});
