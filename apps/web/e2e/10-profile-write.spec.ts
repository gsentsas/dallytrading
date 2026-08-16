/**
 * Première mutation réelle du portail : profil client.
 *
 * L'environnement reste celui de e2e-portal.sh : Odoo/PostgreSQL/Next jetables,
 * comptes et coordonnées synthétiques, aucune donnée de production.
 *
 * Budget : Portal A trois connexions, Portal B une connexion.
 */

import { expect, test } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;
const UPDATED_PHONE = '+221 77 123 45 67';
const UPDATED_STREET = '42 avenue du Test';
const UPDATED_STREET2 = 'Bureau 7';
const UPDATED_ZIP = '11000';
const UPDATED_CITY = 'Dakar Plateau';

test('Portal A modifie son contact; refresh et reconnexion relisent la valeur Odoo', async ({
  browser,
  page,
}) => {
  const updateResponses: string[] = [];
  page.on('response', (response) => {
    if (new URL(response.url()).pathname === '/api/portal/profile') {
      void response.text().then((body) => updateResponses.push(body));
    }
  });

  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  await page.goto('/espace-client/profil');

  await expect(page.getByText('+221 70 000 00 01')).toBeVisible();
  await page.getByRole('button', { name: 'Modifier' }).click();

  await page.getByLabel('Téléphone', { exact: true }).fill(UPDATED_PHONE);
  await page.getByLabel('Adresse', { exact: true }).fill(UPDATED_STREET);
  await page.getByLabel('Complément d’adresse', { exact: true }).fill(UPDATED_STREET2);
  await page.getByLabel('Code postal', { exact: true }).fill(UPDATED_ZIP);
  await page.getByLabel('Ville', { exact: true }).fill(UPDATED_CITY);

  const pending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/portal/profile'
      && response.request().method() === 'PATCH',
  );
  await page.getByRole('button', { name: 'Enregistrer' }).click();
  const response = await pending;

  expect(response.status()).toBe(200);
  expect(response.headers()['cache-control'] ?? '').toContain('no-store');
  await expect(page.getByRole('status')).toContainText('mis à jour');
  await expect(page.getByText(UPDATED_PHONE)).toBeVisible();
  await expect(page.getByText(UPDATED_STREET)).toBeVisible();

  expect(updateResponses.join('\n')).not.toContain('DALLY_E2E_SECRET');
  expect(updateResponses.join('\n')).not.toContain('E2E Beta SARL');

  // Rechargement complet : la page Server Component relit /me chez Odoo.
  await page.reload();
  await expect(page.getByText(UPDATED_PHONE)).toBeVisible();
  await expect(page.getByText(UPDATED_STREET)).toBeVisible();
  await expect(
    page.getByRole('definition').filter({ hasText: 'E2E Alpha SARL (synthetique)' }),
  ).toBeVisible();

  // Déconnexion/reconnexion : la persistance ne dépend d'aucun état React.
  await page.getByRole('button', { name: /Se déconnecter/i }).click();
  await waitForPath(page, '/connexion');
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  await page.goto('/espace-client/profil');
  await expect(page.getByText(UPDATED_PHONE)).toBeVisible();
  await expect(page.getByText(UPDATED_CITY)).toBeVisible();

  // Mass assignment : l'ajout d'une seule clé interdite refuse TOUT le payload.
  const forged = await page.request.patch(`${BASE}/api/portal/profile`, {
    headers: { origin: BASE, 'Content-Type': 'application/json' },
    data: {
      phone: '+221 77 999 99 99',
      partner_id: 1,
      company_id: 1,
      parent_id: 1,
      groups_id: [1],
      credit_limit: 999999,
    },
  });
  expect(forged.status()).toBe(400);
  expect((await forged.json()).error.code).toBe('invalid_request');
  await page.reload();
  await expect(page.getByText(UPDATED_PHONE)).toBeVisible();
  await expect(page.getByText('+221 77 999 99 99')).toHaveCount(0);

  // B garde ses coordonnées et ne reçoit aucune valeur de A.
  const contextB = await browser.newContext();
  const pageB = await contextB.newPage();
  await loginThroughUi(pageB, accounts.portalB);
  await waitForPath(pageB, '/espace-client');
  await pageB.goto('/espace-client/profil');
  await expect(pageB.getByText('+221 70 000 00 02')).toBeVisible();
  expect(await pageB.content()).not.toContain(UPDATED_PHONE);
  expect(await pageB.content()).not.toContain(UPDATED_STREET);
  expect(await pageB.content()).not.toContain('E2E Alpha SARL');
  await contextB.close();
});

test('une origine externe ne peut pas muter une session authentifiée', async ({ page }) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const response = await page.request.patch(`${BASE}/api/portal/profile`, {
    headers: { origin: 'https://evil.example', 'Content-Type': 'application/json' },
    data: { phone: '+221 77 666 66 66' },
  });
  expect(response.status()).toBe(403);

  await page.goto('/espace-client/profil');
  expect(await page.content()).not.toContain('+221 77 666 66 66');
});

test('sans session, une origine valide ne peut rien muter', async ({ request }) => {
  const response = await request.patch(`${BASE}/api/portal/profile`, {
    headers: { origin: BASE, 'Content-Type': 'application/json' },
    data: { phone: '+221 77 555 55 55' },
  });
  expect(response.status()).toBe(401);
  expect(response.headers()['cache-control'] ?? '').toContain('no-store');
});
