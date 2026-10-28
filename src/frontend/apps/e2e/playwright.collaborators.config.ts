import { defineConfig, devices } from '@playwright/test';
import dotenv from 'dotenv';

dotenv.config({
  path: ['./.env.local', './.env'],
  quiet: true,
});

/**
 * The tests of what Collaborators adds to Docs (./collaborators).
 * Apart from the upstream suite: they sign in on their own and run, in
 * order, against the local stack started with `make run`.
 */
export default defineConfig({
  timeout: 240 * 1000,
  testDir: './collaborators',
  outputDir: './test-results/collaborators',
  forbidOnly: !!process.env.CI,
  workers: 1,
  reporter: [['list', { printSteps: true }]],
  use: {
    baseURL: process.env.BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        locale: 'en-US',
        timezoneId: 'Europe/Istanbul',
      },
    },
  ],
});
