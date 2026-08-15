/**
 * Parcours métier complet de Portal A, dans un vrai navigateur.
 *
 * Un seul test, une seule connexion : la limite de débit du login compte par IP,
 * et un test par page en consommerait sept (voir l'en-tête de 01-login.spec.ts).
 * Le parcours suit d'ailleurs ce que fait un client — il navigue, il ne se
 * reconnecte pas à chaque page.
 *
 * Les références ne sont pas codées en dur : elles sont LUES depuis les listes.
 * Un test qui les connaîtrait d'avance passerait même si la navigation était
 * cassée.
 *
 * Budget : 1 tentative de connexion.
 */

import { expect, test, type Page } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

/** Première référence de la première colonne d'une liste, ou `null`. */
async function firstReferenceLink(page: Page): Promise<string | null> {
  const link = page.locator('table tbody tr td:first-child a').first();
  if ((await link.count()) === 0) return null;
  return (await link.textContent())?.trim() ?? null;
}

test('Portal A traverse tout son espace client', async ({ page }) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  // ── Tableau de bord ──
  await expect(page.getByRole('heading', { name: 'Tableau de bord' })).toBeVisible();
  // Les compteurs viennent d'Odoo ; on vérifie qu'ils sont rendus, pas leur valeur
  // (elle dépend du jeu de données et changerait à chaque enrichissement).
  await expect(page.getByRole('link', { name: /Devis/ }).first()).toBeVisible();

  // ── Devis ──
  await page.getByRole('link', { name: 'Devis', exact: true }).first().click();
  await waitForPath(page, '/espace-client/devis');
  const quoteRef = await firstReferenceLink(page);
  expect(quoteRef, 'A doit avoir au moins un devis').toBeTruthy();
  await page.getByRole('link', { name: quoteRef as string }).click();
  await waitForPath(page, `/espace-client/devis/${quoteRef}`);
  await expect(page.getByRole('heading', { name: quoteRef as string })).toBeVisible();
  await expect(page.getByText('Marchandise synthetique A')).toBeVisible();

  // ── Sourcing, propositions comprises ──
  await page.getByRole('link', { name: 'Sourcing', exact: true }).first().click();
  await waitForPath(page, '/espace-client/sourcing');
  const sourcingRef = await firstReferenceLink(page);
  expect(sourcingRef).toBeTruthy();
  await page.getByRole('link', { name: sourcingRef as string }).click();
  await waitForPath(page, `/espace-client/sourcing/${sourcingRef}`);
  await expect(
    page.getByRole('heading', { name: 'Propositions reçues' }),
  ).toBeVisible();
  // La proposition ENVOYÉE est là ; celle restée en brouillon ne doit pas y être.
  await expect(page.getByText('Conditions synthetiques A')).toBeVisible();
  expect(await page.content()).not.toContain('DALLY_E2E_SECRET_DRAFT_PROPOSAL_A');

  // ── Trading ──
  await page.getByRole('link', { name: 'Trading', exact: true }).first().click();
  await waitForPath(page, '/espace-client/trading');
  const tradeRef = await firstReferenceLink(page);
  expect(tradeRef).toBeTruthy();
  await page.getByRole('link', { name: tradeRef as string }).click();
  await waitForPath(page, `/espace-client/trading/${tradeRef}`);
  await expect(page.getByText('Operation synthetique A')).toBeVisible();

  // ── Expéditions : colis et suivi, sans token ──
  await page.getByRole('link', { name: 'Expéditions', exact: true }).first().click();
  await waitForPath(page, '/espace-client/expeditions');
  const shipmentRef = await firstReferenceLink(page);
  expect(shipmentRef).toBeTruthy();
  await page.getByRole('link', { name: shipmentRef as string }).click();
  await waitForPath(page, `/espace-client/expeditions/${shipmentRef}`);
  await expect(page.getByRole('heading', { name: 'Colis' })).toBeVisible();
  await expect(page.getByText('Colis synthetique A')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Suivi' })).toBeVisible();
  await expect(page.getByText('Evenement public A')).toBeVisible();
  // L'événement interne n'apparaît pas, et aucun token de suivi n'est affiché.
  const shipmentHtml = await page.content();
  expect(shipmentHtml).not.toContain('Escale interne A');
  expect(shipmentHtml).not.toContain('token');

  // ── Documents ──
  await page.getByRole('link', { name: 'Documents', exact: true }).first().click();
  await waitForPath(page, '/espace-client/documents');
  // `.first()` : le nom apparaît deux fois, dans la cellule ET dans le libellé
  // accessible du lien de téléchargement (« Télécharger Document publie A »),
  // qui existe pour que ce lien soit compréhensible hors contexte visuel.
  await expect(page.getByText('Document publie A').first()).toBeVisible();
  // Le document NON publié n'est pas listé.
  expect(await page.content()).not.toContain('DALLY_E2E_SECRET_UNPUBLISHED_NAME_A');

  // ── Profil, en lecture seule ──
  await page.getByRole('link', { name: 'Profil', exact: true }).first().click();
  await waitForPath(page, '/espace-client/profil');
  // Deux occurrences légitimes : l'en-tête de navigation et la fiche. On vise
  // celle de la fiche, dans la liste de définitions.
  await expect(page.locator('dl').getByText('E2E Alpha SARL (synthetique)'))
    .toBeVisible();
  // Aucun formulaire, aucun champ modifiable : c'est le périmètre de ce cycle.
  expect(await page.locator('form').count()).toBe(0);
  expect(await page.locator('input, textarea, select').count()).toBe(0);
});

test('le document de A se télécharge et contient ce qu’il doit', async ({ page }) => {
  // Réutilise la session du test précédent ? Non : chaque test a son contexte.
  // Celui-ci consomme donc une seconde tentative de connexion — assumé, le
  // téléchargement mérite son propre test.
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  await page.goto('/espace-client/documents');

  const link = page.getByRole('link', { name: /Télécharger/ }).first();
  const href = await link.getAttribute('href');
  expect(href, 'le lien doit pointer vers notre BFF').toMatch(
    /^\/api\/portal\/documents\/DOC-\d+$/,
  );

  const response = await page.request.get(href as string);
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toBe('application/octet-stream');
  expect(response.headers()['content-disposition']).toContain('attachment;');
  expect(response.headers()['x-content-type-options']).toBe('nosniff');
  expect(response.headers()['cache-control']).toContain('no-store');
  expect(await response.text()).toContain('CONTENU DOCUMENT A');
});
