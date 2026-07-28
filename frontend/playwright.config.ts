import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end configuration.
 *
 * These specs drive the real UI against a running backend, so they are kept out
 * of `npm test` (the fast unit suite) and invoked with `npm run test:e2e`.
 * Only Chromium and a mobile viewport run by default; Firefox and WebKit are
 * available once `npx playwright install firefox webkit` has been run.
 */
const PORT = 3000;
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;

/**
 * Sandboxes and CI images often ship a browser that Playwright did not download
 * itself, so its bundled-revision lookup misses. Set PLAYWRIGHT_CHROMIUM_PATH to
 * use that binary instead of running `playwright install`.
 */
const chromiumPath = process.env.PLAYWRIGHT_CHROMIUM_PATH;
const launchOptions = chromiumPath ? { executablePath: chromiumPath } : {};

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  timeout: 60_000,
  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], launchOptions } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'], launchOptions } },
  ],
  // When E2E_BASE_URL points at an already-running deployment, do not start a
  // second dev server on top of it.
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: 'npm run dev',
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
