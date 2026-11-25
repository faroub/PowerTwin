import { describe, expect, it } from 'vitest';

import { hasPermission, isUserSession, rolePermissions, roleToPermissions } from '../auth';
import type { Permission, UserSession } from '../auth';

function sessionWith(permissions: Permission[]): UserSession {
  return {
    username: 'engineer',
    role: 'ENGINEER',
    permissions: new Set(permissions),
  };
}

describe('Session Presence', () => {
  it('recognises an absent session', () => {
    expect(isUserSession(null)).toBe(false);
  });

  it('rejects a session that carries no username', () => {
    expect(isUserSession(sessionWith(['READ_TELEMETRY']))).toBe(true);
    expect(
      isUserSession({ username: '', role: 'OBSERVER', permissions: new Set<Permission>() }),
    ).toBe(false);
  });
});

describe('Permission Checks', () => {
  it('denies every permission when there is no session', () => {
    expect(hasPermission(null, 'READ_TELEMETRY')).toBe(false);
    expect(hasPermission(null, 'ADMINISTER_SYSTEM')).toBe(false);
  });

  it('grants a permission the session carries', () => {
    expect(hasPermission(sessionWith(['READ_TELEMETRY']), 'READ_TELEMETRY')).toBe(true);
  });

  it('denies a permission the session does not carry', () => {
    expect(hasPermission(sessionWith(['READ_TELEMETRY']), 'MODIFY_SIMULATION')).toBe(false);
  });
});

describe('Role Permission Table', () => {
  it('grants an observer read access only', () => {
    const permissions = roleToPermissions('OBSERVER');

    expect(permissions.has('READ_TELEMETRY')).toBe(true);
    expect(permissions.has('READ_CONFIG')).toBe(true);
    expect(permissions.has('MODIFY_SIMULATION')).toBe(false);
    expect(permissions.has('EXECUTE_SCENARIO')).toBe(false);
    expect(permissions.has('INJECT_FAULT')).toBe(false);
    expect(permissions.has('MANAGE_PLUGINS')).toBe(false);
    expect(permissions.has('ADMINISTER_SYSTEM')).toBe(false);
  });

  it('grants an engineer the simulation controls but not the administrative ones', () => {
    const permissions = roleToPermissions('ENGINEER');

    expect(permissions.has('READ_TELEMETRY')).toBe(true);
    expect(permissions.has('EXECUTE_SCENARIO')).toBe(true);
    expect(permissions.has('INJECT_FAULT')).toBe(true);
    expect(permissions.has('MODIFY_SIMULATION')).toBe(true);
    expect(permissions.has('MANAGE_PLUGINS')).toBe(false);
    expect(permissions.has('ADMINISTER_SYSTEM')).toBe(false);
  });

  it('grants an administrator every declared permission', () => {
    const permissions = roleToPermissions('ADMINISTRATOR');
    const declared: Permission[] = [
      'READ_TELEMETRY',
      'READ_CONFIG',
      'EXECUTE_SCENARIO',
      'INJECT_FAULT',
      'MODIFY_SIMULATION',
      'MANAGE_PLUGINS',
      'ADMINISTER_SYSTEM',
    ];

    for (const permission of declared) {
      expect(permissions.has(permission)).toBe(true);
    }
    expect(permissions.size).toBe(declared.length);
  });

  it('declares a permission set for every role of the table', () => {
    expect(Object.keys(rolePermissions).sort()).toEqual([
      'ADMINISTRATOR',
      'ENGINEER',
      'OBSERVER',
    ]);
  });

  it('grants an unknown role nothing at all', () => {
    expect(roleToPermissions('SUPERUSER').size).toBe(0);
    expect(roleToPermissions('').size).toBe(0);
  });
});
