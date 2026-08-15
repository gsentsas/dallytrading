/**
 * Déconnexion et cookies invalides.
 *
 * Le test le plus important de la suite est celui du retour arrière : c'est le
 * seul qui vérifie le comportement du navigateur lui-même, que ni un test
 * unitaire ni une requête curl ne peuvent reproduire.
 *
 * Budget : 4 tentatives de connexion.
 */

import { expect, test } from '@playwright/test';

import { accounts, apiMe, loginThroughUi, portalCookie, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;

test('déconnexion : cookie retiré, Odoo invalidé, retour arrière stérile', async ({
  page,
}) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  expect(await portalCookie(page)).toBeDefined();

  await page.getByRole('button', { name: /Se déconnecter/i }).click();
  await waitForPath(page, '/connexion');

  expect(await portalCookie(page)).toBeUndefined();
  expect((await apiMe(page.request, BASE)).status()).toBe(401);

  // Le cœur du test : le navigateur ne doit pas ressortir la page privée de son
  // cache d'historique. C'est la raison d'être de la navigation dure.
  await page.goBack();
  await page.waitForLoadState('domcontentloaded');
  expect(await page.content()).not.toContain('E2E Contact A');
  expect(await page.content()).not.toContain('E2E Alpha SARL');

  await page.goForward().catch(() => undefined);
  await page.waitForLoadState('domcontentloaded');
  await page.reload();
  expect(await page.content()).not.toContain('E2E Contact A');

  await page.goto('/espace-client');
  await waitForPath(page, '/connexion');
});

test('un onglet dupliqué après déconnexion n’hérite d’aucune session', async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  await page.getByRole('button', { name: /Se déconnecter/i }).click();
  await waitForPath(page, '/connexion');

  // Même contexte, donc mêmes cookies : c'est ce que fait « dupliquer l'onglet ».
  const duplicate = await context.newPage();
  await duplicate.goto('/espace-client');
  await waitForPath(duplicate, '/connexion');
  expect(await duplicate.content()).not.toContain('E2E Contact A');

  await context.close();
});

test('cookie supprimé, altéré ou inventé : aucun accès', async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const original = await portalCookie(page);
  if (!original) throw new Error('cookie de session absent');

  // (a) supprimé
  await context.clearCookies();
  expect((await apiMe(page.request, BASE)).status()).toBe(401);

  // (b) un seul caractère du chiffré modifié — le tag GCM ne correspond plus
  const parts = original.value.split('.');
  const data = parts[2] as string;
  const flipped = data.slice(0, -1) + (data.slice(-1) === 'A' ? 'B' : 'A');
  await context.addCookies([
    { ...original, value: [parts[0], parts[1], flipped, parts[3]].join('.') },
  ]);
  expect((await apiMe(page.request, BASE)).status()).toBe(401);
  await page.goto('/espace-client');
  await waitForPath(page, '/connexion');

  // (c) valeur arbitraire — celle qui franchit le proxy, et que la page arrête
  await context.clearCookies();
  await context.addCookies([{ ...original, value: 'valeur-totalement-inventee' }]);
  expect((await apiMe(page.request, BASE)).status()).toBe(401);
  await page.goto('/espace-client');
  await waitForPath(page, '/connexion');

  await context.close();
});

test('rejouer un cookie authentique d’avant la déconnexion ne donne rien', async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const stolen = await portalCookie(page);
  if (!stolen) throw new Error('cookie de session absent');

  await page.getByRole('button', { name: /Se déconnecter/i }).click();
  await waitForPath(page, '/connexion');

  /*
   * Ce cookie est authentique, correctement scellé et non expiré : le BFF seul
   * ne peut pas le distinguer d'un cookie valide. Seule l'invalidation côté Odoo
   * l'arrête — c'est précisément ce que ce test prouve, et la raison pour
   * laquelle la déconnexion détruit la session Odoo avant de retirer le cookie.
   */
  await context.addCookies([stolen]);
  expect((await apiMe(page.request, BASE)).status()).toBe(401);
  await page.goto('/espace-client');
  await waitForPath(page, '/connexion');

  await context.close();
});
