/**
 * Seconde moitié : la session Odoo a été détruite entre-temps.
 *
 * Le cookie que le navigateur présente ici est parfaitement valide du point de
 * vue du BFF — bon secret, bon format, non expiré. S'il suffisait, cette page
 * s'afficherait. Elle ne s'affiche pas, parce que le BFF ne lui accorde aucune
 * confiance et redemande à Odoo à chaque accès.
 *
 * C'est la démonstration la plus directe de la règle qui gouverne toute la
 * couche : **le cookie ne prouve rien**.
 *
 * Budget : 0 tentative de connexion.
 */

import { expect, test } from '@playwright/test';

import { PORTAL_COOKIE, apiMe, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;

test.use({ storageState: process.env.E2E_STATE_PATH });

test('un cookie authentique ne suffit pas quand Odoo a oublié la session', async ({
  page,
  context,
}) => {
  // Le cookie est bien là : le refus qui suit ne vient donc pas de son absence.
  const cookie = (await context.cookies()).find((c) => c.name === PORTAL_COOKIE);
  expect(cookie, 'le cookie capturé doit être présent').toBeDefined();
  expect(cookie?.value.split('.')[0]).toBe('v1');

  expect((await apiMe(page.request, BASE)).status()).toBe(401);

  await page.goto('/espace-client');
  await waitForPath(page, '/connexion');
  expect(await page.content()).not.toContain('E2E Contact A');
});
