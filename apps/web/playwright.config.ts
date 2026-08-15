import { defineConfig, devices } from '@playwright/test';

/**
 * Configuration E2E — environnement isolé uniquement.
 *
 * Ces tests exigent une instance Next de test ET une instance Odoo de test,
 * toutes deux jetables. Ils ne sont **jamais** exécutés contre la production :
 * ils créent des sessions, tentent des connexions invalides et invalident des
 * sessions Odoo.
 *
 * Rien n'est démarré automatiquement (pas de `webServer`) : lancer un serveur
 * implicitement rendrait trop facile de le pointer par accident vers une base
 * réelle. La cible est fournie explicitement, et le test refuse de tourner sans.
 *
 * Voir docs/PORTAL.md §10 pour la procédure de mise en place.
 */

const baseURL = process.env.E2E_BASE_URL;

if (!baseURL) {
  throw new Error(
    'E2E_BASE_URL est requis. Ces tests ne doivent jamais viser la production — ' +
      'voir docs/PORTAL.md.',
  );
}

// Garde-fou explicite : même avec une variable mal renseignée, la suite refuse
// de s'exécuter contre un domaine de production.
if (/dallytrading\.com/i.test(baseURL)) {
  throw new Error(
    `E2E_BASE_URL pointe vers un domaine de production (${baseURL}). Refus.`,
  );
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  // Les comptes sont partagés entre les tests et la limitation de débit du login
  // compte par identifiant : en parallèle, les tests se freineraient mutuellement.
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'off',
    // Aucune capture : les pages contiennent des sessions actives.
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
