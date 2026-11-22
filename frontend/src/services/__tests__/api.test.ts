import { describe, expect, it } from 'vitest';

import { platformSession } from '../api';
import type { UserSession } from '../auth';

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
});
