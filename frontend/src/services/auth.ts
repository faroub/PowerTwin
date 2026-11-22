/**
 * Platform session model and UI-access helpers.
 *
 * The role/permission sets are deliberately read-only on the frontend: the backend
 * validates permissions server-side for every endpoint. The UI uses this information
 * only for rendering, never for enforcing access.
 *
 * NOTE: Local credential storage exists only on the backend. The frontend neverVALIDATES
 * or stores user passwords; every login request is forwarded to the backend
 * (`/api/v1/auth/login`) for authentication.
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

/** Mirrors the backend `USER_ROLES` RBAC table for UI rendering only. */
export const rolePermissions: RolePermissions = {
  OBSERVER: new Set(['READ_TELEMETRY', 'READ_CONFIG']),
  ENGINEER: new Set([
    'READ_TELEMETRY',
    'READ_CONFIG',
    'EXECUTE_SCENARIO',
    'INJECT_FAULT',
    'MODIFY_SIMULATION',
  ]),
  ADMINISTRATOR: new Set([
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

/**
 * Translate the role reported by the backend (`OBSERVER`, `ENGINEER`, `ADMINISTRATOR`)
 * into the frontend permission sets. Unknown roles receive an empty permission set;
 * the backend remains the authority for permission enforcement on every request.
 */
export function roleToPermissions(role: string): Set<Permission> {
  const known = rolePermissions[role];
  if (!known) {
    return new Set<Permission>();
  }
  return known;
}
