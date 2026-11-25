/**
 * Global setup for the Vitest component suite.
 *
 * The suite renders the real HMI components, so it needs three things that a
 * bare Vitest run does not provide:
 *
 * 1. The jest-dom matchers, so that assertions read as behaviour
 *    ("the banner shows the simulation mode") rather than as DOM plumbing.
 * 2. An unmount between tests, so that a component's polling interval cannot
 *    outlive the test that installed it and leak calls into the next one.
 * 3. A cleared platform session, so that the in-memory token of one test can
 *    never be observed by the next one. The session is a module-level
 *    singleton by design — it is what keeps the token out of client storage —
 *    so the suite has to reset it explicitly.
 */

import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

import { platformSession } from '../services/api';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  platformSession.clear();
});
