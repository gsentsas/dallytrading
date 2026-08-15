/**
 * Redirection ouverte et contrôle d'origine.
 *
 * La matrice exhaustive des formes refusées est couverte par les tests unitaires
 * de `safeNextPath` (dix cas, dont `//evil.example` et `/\evil.example`). Ici on
 * vérifie le câblage réel : que le paramètre traverse bien la page, le formulaire
 * et la navigation du navigateur sans échapper au filtre.
 *
 * Budget : 3 tentatives de connexion. Les refus d'origine n'en consomment aucune,
 * le contrôle ayant lieu avant la limitation de débit.
 */

import { expect, test } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;

for (const target of ['https://evil.example/phish', '//evil.example']) {
  test(`next=${target} ne fait pas sortir du portail`, async ({ page }) => {
    await loginThroughUi(page, accounts.portalA, encodeURIComponent(target));
    await waitForPath(page, '/espace-client');
    expect(new URL(page.url()).host).toBe(new URL(BASE).host);
  });
}

test('une destination interne du portail est conservée', async ({ page }) => {
  // /espace-client/documents n'existe pas encore : la page répondra 404. Ce qui
  // est testé ici est la DESTINATION, pas l'existence de la route.
  await loginThroughUi(page, accounts.portalA, encodeURIComponent('/espace-client/documents'));
  await waitForPath(page, '/espace-client/documents');
  expect(new URL(page.url()).host).toBe(new URL(BASE).host);
});

test('une origine externe est refusée sur login et sur logout', async ({ request }) => {
  const login = await request.post(`${BASE}/api/portal/auth/login`, {
    headers: { origin: 'https://evil.example', 'Content-Type': 'application/json' },
    data: { login: accounts.portalA.login(), password: accounts.portalA.password() },
  });
  expect(login.status()).toBe(403);

  const logout = await request.post(`${BASE}/api/portal/auth/logout`, {
    headers: { origin: 'https://evil.example' },
  });
  expect(logout.status()).toBe(403);
});
