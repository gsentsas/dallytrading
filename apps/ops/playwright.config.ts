import { defineConfig, devices } from '@playwright/test';

/**
 * Configuration Playwright.
 *
 * Un seul navigateur, au format d'un téléphone : l'application est utilisée
 * d'une main dans un entrepôt, pas sur un bureau. Le serveur est démarré à
 * part (voir docs/OPS-BANC.md) plutôt que par `webServer`, parce qu'il doit
 * pointer vers un banc Odoo dont l'adresse change d'une machine à l'autre.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.OPS_E2E_BASE_URL ?? 'http://127.0.0.1:3020',
    ...devices['Pixel 7'],
  },
  projects: [{ name: 'mobile-chromium' }],
});
