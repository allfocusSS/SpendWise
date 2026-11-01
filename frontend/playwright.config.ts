import { defineConfig, devices } from '@playwright/test'

import { BASE_URL } from './e2e/support/stack'

/**
 * End-to-end tests in a real browser against the real stack: the production frontend build,
 * FastAPI and PostgreSQL, started with Docker Compose by e2e/global-setup.ts.
 *
 * Run with `make e2e` from the repo root (or `npm run e2e` here). See README, "End-to-end tests".
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',

  // Every test signs up its own users, so tests are independent and can run in parallel.
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 45_000,
  expect: { timeout: 10_000 },

  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',

  use: {
    baseURL: BASE_URL,
    locale: 'en-GB',
    // Fixed so "today" and "this month" mean the same thing on every machine and in CI.
    timezoneId: 'Asia/Almaty',
    // Failure artifacts: a trace (DOM snapshots, network, console) and a screenshot. No video:
    // the trace already shows every step.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },

  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      // Phone-sized smoke run: only the tests tagged @mobile.
      name: 'mobile-chromium',
      use: { ...devices['Pixel 7'] },
      grep: /@mobile/,
    },
  ],
})
