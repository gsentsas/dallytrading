import { expect, test, type Page } from '@playwright/test';

/**
 * Le premier écran métier, de bout en bout.
 *
 * Le serveur interrogé est un vrai Odoo de banc, où quatre départs existent :
 * un aérien et un maritime en collecte, un routier en collecte, et un aérien
 * en brouillon. Seuls les deux premiers doivent apparaître — et c'est Odoo,
 * pas le navigateur, qui l'a décidé.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const AERIEN = 'AIR-DSS-CDG-TEST-001';
const MARITIME = 'SEA-DKR-LEH-TEST-001';
const ROUTIER = 'ROAD-DKR-BKO-TEST-001';
const BROUILLON = 'AIR-DSS-CDG-TEST-DRAFT';

async function ouvrirLaReception(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(OPERATEUR.login);
  await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await expect(page.getByRole('heading', { name: 'Réceptionner un colis' })).toBeVisible();
}

test('le logisticien atteint la liste des départs depuis l’accueil', async ({ page }) => {
  await ouvrirLaReception(page);
  await expect(page.getByText('Choisissez le prochain départ')).toBeVisible();
});

test('les départs ouverts s’affichent avec leur route en clair', async ({ page }) => {
  await ouvrirLaReception(page);
  await expect(page.getByText(AERIEN)).toBeVisible();
  await expect(page.getByText('Dakar → Paris')).toBeVisible();
  await expect(page.getByText(MARITIME)).toBeVisible();
  await expect(page.getByText('Dakar → Le Havre')).toBeVisible();
});

test('le routier et le brouillon restent invisibles', async ({ page }) => {
  await ouvrirLaReception(page);
  // Phase 1 : uniquement des colis, uniquement des collectes ouvertes.
  await expect(page.getByText(ROUTIER)).toHaveCount(0);
  await expect(page.getByText(BROUILLON)).toHaveCount(0);
});

test('les échéances s’affichent en toutes lettres, sans en inventer', async ({ page }) => {
  await ouvrirLaReception(page);
  await expect(page.getByText('Départ prévu : 05 septembre 2026')).toBeVisible();
  // Le maritime de banc n'a pas de date de départ : une seule ligne « Départ
  // prévu » doit exister sur l'écran.
  await expect(page.getByText(/Départ prévu/)).toHaveCount(1);
});

test('la collecte qui ferme le plus tôt est en tête', async ({ page }) => {
  await ouvrirLaReception(page);
  const references = await page.locator('.reference').allTextContents();
  expect(references).toEqual([AERIEN, MARITIME]);
});

test('sélectionner un départ mène à l’étape suivante en le portant', async ({ page }) => {
  await ouvrirLaReception(page);
  await page.locator('section.carte', { hasText: AERIEN })
    .getByRole('link', { name: 'Sélectionner' }).click();

  await expect(page).toHaveURL(new RegExp(`/reception/client\\?consolidation=${AERIEN}$`));
  await expect(page.getByRole('heading', { name: 'Rechercher le client' })).toBeVisible();
  await expect(page.getByTestId('consolidation-selectionnee')).toHaveText(AERIEN);
});

test('l’écran n’offre aucun moyen de créer ou fermer une collecte', async ({ page }) => {
  await ouvrirLaReception(page);
  // La création reste une décision de back-office.
  for (const interdit of ['Créer', 'Nouvelle collecte', 'Clôturer', 'Fermer']) {
    await expect(page.getByRole('button', { name: interdit })).toHaveCount(0);
  }
});

test('aucun identifiant Odoo ni champ sensible ne descend dans la page', async ({ page }) => {
  await ouvrirLaReception(page);
  const html = await page.content();
  for (const interdit of ['mawb', 'hawb', 'shipper', 'consignee', 'invoice',
                          'intake_sequence', 'session_id=', 'API_KEY', 'freight:']) {
    expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
  }
});

test('un visiteur anonyme ne voit pas les départs', async ({ page, request }) => {
  await page.goto('/reception');
  await expect(page).toHaveURL(/\/connexion$/);

  const anonyme = await request.get('/api/consolidations');
  expect(anonyme.status()).toBe(401);
});
