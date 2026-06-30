// @ts-check
const { defineConfig, devices } = require('@playwright/test');
const path = require('path');

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:8080';
const STORAGE_STATE = path.join(__dirname, '.auth', 'state.json');

/**
 * Playwright config for the ITCJ Helpdesk E2E suite.
 *
 * - baseURL points at the dockerized stack (nginx -> backend) on :8080.
 * - globalSetup mints a JWT inside the backend container and writes a
 *   storageState with the `itcj_token` cookie (see global-setup.js).
 * - Every test inherits that storageState, so the suite runs authenticated
 *   as a helpdesk admin without ever touching the login UI.
 */
module.exports = defineConfig({
  testDir: __dirname,
  globalSetup: require.resolve('./global-setup.js'),
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    storageState: STORAGE_STATE,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    actionTimeout: 7_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
