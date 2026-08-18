import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: '.',
  timeout: 90000,
  expect: { timeout: 20000 },
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: process.env.ODOO_URL, screenshot: 'only-on-failure', trace: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
