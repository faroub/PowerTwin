import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end configuration for the HMI.
 *
 * The suite runs against the *built* artefact, served by `vite preview` on the
 * loopback interface. Binding to 127.0.0.1 is deliberate: the HMI must never
 * be reachable from an untrusted network (safety rule 12), and an
 * end-to-end run must never be able to address a real installation.
 *
 * There is no backend behind the preview server. Every `/api/v1/**` request is
 * answered by the mock in `e2e/mockPlatform.ts`, which aborts any path it
 * does not model and blocks every host that is not the preview server. The
 * specs assert that neither happened.
 */

const PREVIEW_HOST = '127.0.0.1';
const PREVIEW_PORT = 4173;
const PREVIEW_URL = `http://${PREVIEW_HOST}:${PREVIEW_PORT}`;

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['list']],
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: PREVIEW_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npm run preview -- --host ${PREVIEW_HOST} --port ${PREVIEW_PORT} --strictPort`,
    url: PREVIEW_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
