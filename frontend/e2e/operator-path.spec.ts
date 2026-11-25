import { expect, test } from '@playwright/test';

import { installMockPlatform, logIn, MOCK_TOKEN, openView } from './mockPlatform';

/**
 * The operator path.
 *
 * Log in → read the overview → act on the simulation engine → observe the
 * result → log out. The spec proves that the shipped artefact really performs
 * that path, and that the session token travels with the action but never
 * reaches any client-side storage.
 */
test.describe('Operator path', () => {
  test('logs in, reads the overview, pauses the engine and logs out', async ({ page }) => {
    const platform = await installMockPlatform(page);

    await page.goto('/');

    // --- Login ---------------------------------------------------------
    await expect(
      page.getByRole('heading', { level: 1, name: 'PowerTwin BESS Platform' }),
    ).toBeVisible();
    // The shelter notice is a <strong> followed by prose, so the assertion
    // has to be made on the element that carries the whole sentence.
    await expect(page.getByText(/LOGIN SHELTER:/).locator('..')).toContainText(
      'No hardware equipment is detected during login',
    );

    await logIn(page);

    // The session token must not have been written anywhere persistent.
    const storageAfterLogin = await page.evaluate(() => ({
      local: Object.keys(window.localStorage),
      session: Object.keys(window.sessionStorage),
      cookie: document.cookie,
    }));
    expect(storageAfterLogin).toEqual({ local: [], session: [], cookie: '' });
    expect(await page.content()).not.toContain(MOCK_TOKEN);

    // --- Read the overview ---------------------------------------------
    await expect(page.getByText('4.25 MW')).toBeVisible();
    await expect(page.getByText('50.00 Hz | 33.00 kV')).toBeVisible();
    await expect(page.getByText('SIMULATED DATA ONLY:')).toBeVisible();

    // --- Act on the engine ---------------------------------------------
    await openView(page, 'Simulation Control');
    await expect(page.getByRole('heading', { level: 1, name: 'Simulation Control' })).toBeVisible();
    await expect(page.getByText('RUNNING', { exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'PAUSE' }).click();

    // The operator is told what is about to happen, and that nothing real is
    // being touched.
    await expect(page.getByText('Confirm Engine Control Action')).toBeVisible();
    await expect(
      page.getByText('Are you sure you want to execute: Pause Engine?'),
    ).toBeVisible();
    await expect(page.getByText(/Zero real equipment is targeted/i)).toBeVisible();

    await page.getByRole('button', { name: /CONFIRM & EXECUTE/ }).click();

    // --- Observe the result --------------------------------------------
    await expect(page.getByText('[SUCCESS]', { exact: true })).toBeVisible();
    await expect(page.getByText('PAUSED', { exact: true })).toBeVisible();

    const controlRequest = platform.requests.find(
      (request) => request.path === '/api/v1/simulation/control',
    );
    expect(controlRequest).toBeDefined();
    expect(controlRequest?.method).toBe('POST');
    expect(controlRequest?.body).toEqual({ action: 'PAUSE' });
    expect(controlRequest?.authorization).toBe(`Bearer ${MOCK_TOKEN}`);

    // --- Log out -------------------------------------------------------
    await page.getByText('LOGOUT').click();
    await expect(
      page.getByRole('heading', { level: 1, name: 'PowerTwin BESS Platform' }),
    ).toBeVisible();
    await expect(page.getByText('Log in to the HMI session')).toBeVisible();

    const storageAfterLogout = await page.evaluate(() => ({
      local: Object.keys(window.localStorage),
      session: Object.keys(window.sessionStorage),
      cookie: document.cookie,
    }));
    expect(storageAfterLogout).toEqual({ local: [], session: [], cookie: '' });
    expect(await page.content()).not.toContain(MOCK_TOKEN);

    // The mock must not have been asked for anything it does not model, and
    // the page must not have tried to reach any host but the preview server.
    expect(platform.unknownPaths).toEqual([]);
    expect(platform.blockedHosts).toEqual([]);
  });

  test('sends no authorisation header before the operator logs in', async ({ page }) => {
    const platform = await installMockPlatform(page);

    await page.goto('/');
    await expect(page.getByText('Log in to the HMI session')).toBeVisible();

    await logIn(page);

    const loginRequest = platform.requests.find(
      (request) => request.path === '/api/v1/auth/login',
    );
    expect(loginRequest).toBeDefined();
    // The credential exchange itself must not carry a token: the operator
    // does not have one yet.
    expect(loginRequest?.authorization).toBeUndefined();

    // The control endpoint must not have been touched by an anonymous page.
    expect(
      platform.requests.some((request) => request.path === '/api/v1/simulation/control'),
    ).toBe(false);
  });
});
