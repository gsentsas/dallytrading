/**
 * Décision devis de bout en bout sur la pile jetable uniquement.
 *
 * Les quatre devis viennent de e2e-seed.py, avec des sale.order synthétiques
 * réellement en état `sent`. Aucune donnée de production n'est utilisée.
 */

import { expect, test, type Page } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;
const REJECTION_REASON = 'DALLY_E2E_QUOTE_REJECTION_REASON';

async function referenceFor(page: Page, label: string): Promise<string> {
  await page.goto('/espace-client/devis');
  const row = page.getByRole('row').filter({ hasText: label });
  await expect(row).toHaveCount(1);
  const reference = (await row.getByRole('link').first().textContent())?.trim();
  expect(reference, `référence absente pour ${label}`).toBeTruthy();
  return reference as string;
}

function decisionUrl(reference: string): string {
  return `${BASE}/api/portal/quotes/${encodeURIComponent(reference)}/decision`;
}

test('A accepte/refuse; concurrence et reconnexion relisent la décision Odoo', async ({
  browser,
  page,
}) => {
  const decisionBodies: string[] = [];
  page.on('response', (response) => {
    if (new URL(response.url()).pathname.endsWith('/decision')) {
      void response.text().then((body) => decisionBodies.push(body));
    }
  });

  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const acceptRef = await referenceFor(page, 'Quote A Accept');
  const rejectRef = await referenceFor(page, 'Quote A Reject');
  const concurrentRef = await referenceFor(page, 'Quote A Concurrent');

  await page.goto(`/espace-client/devis/${encodeURIComponent(acceptRef)}`);
  await expect(page.getByRole('button', { name: 'Accepter le devis' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refuser le devis' })).toBeVisible();
  await page.getByRole('button', { name: 'Accepter le devis' }).click();
  await expect(
    page.getByRole('group', { name: 'Confirmer l’acceptation' }),
  ).toBeVisible();

  const acceptedPending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith('/decision')
      && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Confirmer l’acceptation' }).click();
  const accepted = await acceptedPending;
  expect(accepted.status()).toBe(200);
  expect(accepted.headers()['cache-control'] ?? '').toContain('no-store');
  await expect(page.getByRole('status')).toContainText('acceptation');
  await expect(page.getByText('Accepté', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Accepter le devis' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Refuser le devis' })).toHaveCount(0);

  // Même décision : 200 idempotent. Décision opposée : 409 conflict.
  const repeated = await page.request.post(decisionUrl(acceptRef), {
    headers: { origin: BASE, 'Content-Type': 'application/json' },
    data: { decision: 'accept' },
  });
  expect(repeated.status()).toBe(200);
  const opposite = await page.request.post(decisionUrl(acceptRef), {
    headers: { origin: BASE, 'Content-Type': 'application/json' },
    data: { decision: 'reject' },
  });
  expect(opposite.status()).toBe(409);
  expect((await opposite.json()).error.code).toBe('conflict');

  await page.goto(`/espace-client/devis/${encodeURIComponent(rejectRef)}`);
  await page.getByRole('button', { name: 'Refuser le devis' }).click();
  await page.getByLabel('Motif du refus (facultatif)').fill(REJECTION_REASON);
  const rejectedPending = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith('/decision')
      && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Confirmer le refus' }).click();
  expect((await rejectedPending).status()).toBe(200);
  await expect(page.getByRole('status')).toContainText('refus');
  await expect(page.getByText('Refusé', { exact: true })).toBeVisible();

  // Deux requêtes simultanées : une transition, puis un succès idempotent.
  const concurrentResponses = await Promise.all([
    page.request.post(decisionUrl(concurrentRef), {
      headers: { origin: BASE, 'Content-Type': 'application/json' },
      data: { decision: 'accept' },
    }),
    page.request.post(decisionUrl(concurrentRef), {
      headers: { origin: BASE, 'Content-Type': 'application/json' },
      data: { decision: 'accept' },
    }),
  ]);
  expect(concurrentResponses.map((response) => response.status()).sort())
    .toEqual([200, 200]);

  await page.goto(`/espace-client/devis/${encodeURIComponent(concurrentRef)}`);
  await expect(page.getByText('Accepté', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Accepter le devis' })).toHaveCount(0);

  // Refresh puis logout/login : aucun état React ne suffit à faire passer ce test.
  await page.goto(`/espace-client/devis/${encodeURIComponent(acceptRef)}`);
  await page.reload();
  await expect(page.getByText('Accepté', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /Se déconnecter/i }).click();
  await waitForPath(page, '/connexion');
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  await page.goto(`/espace-client/devis/${encodeURIComponent(rejectRef)}`);
  await expect(page.getByText('Refusé', { exact: true })).toBeVisible();

  // B conserve son propre devis et ne voit aucun des libellés A.
  const contextB = await browser.newContext();
  const pageB = await contextB.newPage();
  await loginThroughUi(pageB, accounts.portalB);
  await waitForPath(pageB, '/espace-client');
  const quoteBRef = await referenceFor(pageB, 'Quote B Sent');
  expect(await pageB.content()).not.toContain('Quote A Accept');
  expect(await pageB.content()).not.toContain('Quote A Reject');
  await pageB.goto(`/espace-client/devis/${encodeURIComponent(quoteBRef)}`);
  await expect(pageB.getByRole('button', { name: 'Accepter le devis' })).toBeVisible();
  await contextB.close();

  const cross = await page.goto(
    `/espace-client/devis/${encodeURIComponent(quoteBRef)}`,
  );
  expect(cross?.status()).toBe(404);

  const network = decisionBodies.join('\n');
  for (const forbidden of [
    REJECTION_REASON,
    'DALLY_E2E_SECRET',
    'margin',
    'commission',
    'internal_notes',
    'supplier_cost',
    'x-api-key',
  ]) {
    expect(network.toLowerCase()).not.toContain(forbidden.toLowerCase());
  }
});

test('CSRF, session et mass assignment échouent avant toute mutation', async ({ page, request }) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  const reference = await referenceFor(page, 'Quote A Security');

  const forged = await page.request.post(decisionUrl(reference), {
    headers: { origin: BASE, 'Content-Type': 'application/json' },
    data: {
      decision: 'accept',
      state: 'won',
      partner_id: 1,
      margin: 0,
      user_id: 1,
    },
  });
  expect(forged.status()).toBe(400);
  expect((await forged.json()).error.code).toBe('invalid_request');

  const evil = await page.request.post(decisionUrl(reference), {
    headers: { origin: 'https://evil.example', 'Content-Type': 'application/json' },
    data: { decision: 'accept' },
  });
  expect(evil.status()).toBe(403);

  const missingOrigin = await page.request.post(decisionUrl(reference), {
    headers: { 'Content-Type': 'application/json' },
    data: { decision: 'accept' },
  });
  expect(missingOrigin.status()).toBe(403);

  const noSession = await request.post(decisionUrl(reference), {
    headers: { origin: BASE, 'Content-Type': 'application/json' },
    data: { decision: 'accept' },
  });
  expect(noSession.status()).toBe(401);
  expect(noSession.headers()['cache-control'] ?? '').toContain('no-store');

  await page.goto(`/espace-client/devis/${encodeURIComponent(reference)}`);
  await expect(page.getByText('Devis transmis', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Accepter le devis' })).toBeVisible();
});
