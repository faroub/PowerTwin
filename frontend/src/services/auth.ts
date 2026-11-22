/**
 * Platform session model and UI-access helpers.
 *
 * The role/permission sets are deliberately read-only on the frontend: the backend
 * validates permissions server-side for every endpoint. The UI uses this information
 * only for rendering, never for enforcing access.
 */

export type Permission =
  | 'READ_TELEMETRY'
  | 'READ_CONFIG'
  | 'EXECUTE_SCENARIO'
  | 'INJECT_FAULT'
  | 'MODIFY_SIMULATION'
  | 'MANAGE_PLUGINS'
  | 'ADMINISTER_SYSTEM';

export interface UserSession {
  username: string;
  role: string;
  permissions: Set<Permission>;
}

/** Map of user role → set of granted permission identifiers. */
export type RolePermissions = Record<string, Set<Permission>>;

/** Mirrors the backend `ROLE_PERMISSIONS` RBAC table for UI rendering only. */
export const rolePermissions: RolePermissions = {
  observer: new Set(['READ_TELEMETRY', 'READ_CONFIG']),
  engineer: new Set([
    'READ_TELEMETRY',
    'READ_CONFIG',
    'EXECUTE_SCENARIO',
    'INJECT_FAULT',
    'MODIFY_SIMULATION',
  ]),
  admin: new Set([
    'READ_TELEMETRY',
    'READ_CONFIG',
    'EXECUTE_SCENARIO',
    'INJECT_FAULT',
    'MODIFY_SIMULATION',
    'MANAGE_PLUGINS',
    'ADMINISTER_SYSTEM',
  ]),
};

/** UI-level shortcut for checking whether the platform session is logged in. */
export function isUserSession(session: UserSession | null): boolean {
  return session !== null && session.username.length > 0;
}

export function hasPermission(session: UserSession | null, permission: Permission): boolean {
  if (!session) {
    return false;
  }
  return session.permissions.has(permission);
}

type CmdResult<T> = { ok: true; data: T } | { ok: false; error: string };

/** Known development user accounts, mirrored from the backend development database. */
export const devUsers: Record<string, string> = {
  observer: 'observer123',
  engineer: 'engineer123',
  admin: 'admin123',
};

/**
 * Validate local user credentials against the pre-seeded development account set.
 *
 * In production (non-development ENVIRONMENT in the backend) this endpoint returns 401
 * and the frontend will report an authentication failure.
 */
export async function checkLocalLogin(username: string, password: string): Promise<CmdResult<void>> {
  const expected = devUsers[username.toLowerCase()];
  if (!expected || expected !== password) {
    return { ok: false, error: 'Incorrect username or password.' };
  }
  return { ok: true, data: undefined };
}
