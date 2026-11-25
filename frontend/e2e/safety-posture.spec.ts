import { expect, test } from '@playwright/test';

import { installMockPlatform, logIn, openView } from './mockPlatform';

/**
 * The safety posture of the shipped HMI.
 *
 * These specs are not about features. They pin the behaviour the platform's
 * safety rules depend on, so that a later change cannot quietly remove it:
 *
 * - The HMI states that it is a simulation and reaches no hardware.
 * - A backend that is not ready is reported as disconnected. The HMI does not
 *   invent plausible numbers to fill the gap (safety rule 11: never silently
 *   fall back).
 * - A control action the backend refuses is reported as a failure, and the
 *   engine state is not quietly set to a successful one.
 */
test.describe('Safety posture', () => {
  test('states that the platform is a simulation reaching no hardware', async ({ page }) => {
    await installMockPlatform(page);

    await page.goto('/');
    await logIn(page);

    const footer = page.locator('.safety-footer');
    await expect(footer).toContainText('SIMULATION ONLY');
    await expect(footer).toContainText('No hardware equipment is detected');

    await expect(page.getByText('SIMULATED DATA ONLY:')).toBeVisible();
  });

  test('reports the backend as disconnected when the health check fails', async ({ page }) => {
    await installMockPlatform(page, {
      overrides: {
        '/api/v1/info': { status: 503, body: { detail: 'the simulation engine is not ready' } },
      },
    });

    await page.goto('/');
    await logIn(page);

    await expect(page.getByText(/API:/)).toContainText('DISCONNECTED');
  });

  test('shows no telemetry when the plant overview cannot be read', async ({ page }) => {
    await installMockPlatform(page, {
      overrides: {
        '/api/v1/overview': { status: 503, body: { detail: 'not ready' } },
      },
    });

    await page.goto('/');
    await logIn(page);

    // The overview must say that it is not connected rather than display a
    // stale or invented power figure.
    await expect(page.getByText('NOT CONNECTED')).toBeVisible();
    await expect(page.getByText('4.25 MW')).toHaveCount(0);
  });

  test('reports a refused control action as a failure', async ({ page }) => {
    await installMockPlatform(page, {
      overrides: {
        '/api/v1/simulation/control': {
          status: 503,
          body: { detail: { message: 'Simulation engine is not connected.' } },
        },
      },
    });

    await page.goto('/');
    await logIn(page);
    await openView(page, 'Simulation Control');

    await page.getByRole('button', { name: 'PAUSE' }).click();
    await page.getByRole('button', { name: /CONFIRM & EXECUTE/ }).click();

    await expect(page.getByText('[NOT_CONNECTED]', { exact: true })).toBeVisible();
    await expect(page.getByText('PAUSED', { exact: true })).toHaveCount(0);
  });
});
