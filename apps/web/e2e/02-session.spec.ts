/**
 * Session établie : ce que le navigateur détient, et ce qu'il ne voit pas.
 *
 * Budget : 5 tentatives de connexion (voir l'en-tête de 01-login.spec.ts).
 */

import { expect, test, type Page } from '@playwright/test';

import { PORTAL_COOKIE, accounts, loginThroughUi, portalCookie, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;

/** Tout ce que du JavaScript de page peut atteindre. */
async function browserVisibleState(page: Page) {
  return page.evaluate(() => ({
    documentCookie: document.cookie,
    localStorage: JSON.stringify(window.localStorage),
    sessionStorage: JSON.stringify(window.sessionStorage),
    html: document.documentElement.outerHTML,
  }));
}

test('aucun secret n’est atteignable depuis le navigateur', async ({ page }) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const state = await browserVisibleState(page);

  for (const needle of [
    accounts.portalA.password(),
    process.env.E2E_PORTAL_SECRET as string,
    'session_id',
    PORTAL_COOKIE,
  ]) {
    // `document.cookie` ne voit rien : le cookie est HttpOnly. C'est ce qui rend
    // inopérant un script injecté dans la page.
    expect(state.documentCookie).not.toContain(needle);
    expect(state.localStorage).not.toContain(needle);
    expect(state.sessionStorage).not.toContain(needle);
    expect(state.html).not.toContain(needle);
  }

  // Rien du tout, pas même une clé anodine : le portail n'écrit aucun état côté
  // navigateur, et cette assertion échouera dès que ce sera le cas.
  expect(state.localStorage).toBe('{}');
  expect(state.sessionStorage).toBe('{}');
});

test('le cookie est HttpOnly, Lax, sur / et host-only', async ({ page }) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const cookie = await portalCookie(page);
  expect(cookie).toBeDefined();
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe('Lax');
  expect(cookie?.path).toBe('/');

  /*
   * HOST-ONLY — l'assertion la moins évidente du fichier.
   *
   * Chromium préfixe d'un point le domaine des cookies déclarés avec `Domain=`.
   * L'absence de ce point prouve qu'aucun `Domain` n'a été posé, donc que le
   * cookie ne partira jamais vers un sous-domaine — en production, vers
   * crm.dallytrading.com, qui n'en a aucun usage. Une session envoyée à un hôte
   * qui n'en a pas besoin, c'est une session exposée pour rien.
   */
  expect(cookie?.domain.startsWith('.')).toBe(false);

  // Contenu opaque et versionné.
  expect(cookie?.value.split('.')[0]).toBe('v1');
  expect(cookie?.value).not.toContain('session_id');
});

test('A et B ne voient chacun que leur propre société', async ({ browser }) => {
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  const pageA = await contextA.newPage();
  const pageB = await contextB.newPage();

  await loginThroughUi(pageA, accounts.portalA);
  await waitForPath(pageA, '/espace-client');
  await loginThroughUi(pageB, accounts.portalB);
  await waitForPath(pageB, '/espace-client');

  const htmlA = await pageA.content();
  const htmlB = await pageB.content();

  expect(htmlA).toContain('E2E Alpha SARL');
  expect(htmlA).not.toContain('E2E Beta SARL');
  expect(htmlA).not.toContain('E2E Contact B');

  expect(htmlB).toContain('E2E Beta SARL');
  expect(htmlB).not.toContain('E2E Alpha SARL');
  expect(htmlB).not.toContain('E2E Contact A');

  await contextA.close();
  await contextB.close();
});

test('sans session, la page privée renvoie vers /connexion', async ({ page }) => {
  await page.goto('/espace-client');
  await waitForPath(page, '/connexion');
  // La destination demandée est conservée pour y revenir après connexion.
  expect(new URL(page.url()).searchParams.get('next')).toBe('/espace-client');
});

test('les réponses privées interdisent toute mise en cache', async ({ page }) => {
  const pagePromise = page.waitForResponse(
    (r) => new URL(r.url()).pathname === '/espace-client' && r.request().method() === 'GET',
  );
  await loginThroughUi(page, accounts.portalA);
  const pageResponse = await pagePromise;
  expect(pageResponse.headers()['cache-control'] ?? '').toMatch(/no-store/);

  const me = await page.request.get(`${BASE}/api/portal/me`, { headers: { origin: BASE } });
  expect(me.status()).toBe(200);

  /*
   * On vérifie la PROPRIÉTÉ, pas la chaîne exacte.
   *
   * Next réécrit le `Cache-Control` des Route Handlers dynamiques et n'émet que
   * `no-store`, sans la directive `private` posée dans le code. Exiger `private`
   * ferait échouer ce test sur un comportement du framework, alors que `no-store`
   * est strictement plus fort : il interdit à tout cache — partagé ou privé — de
   * stocker la réponse.
   */
  expect(me.headers()['cache-control'] ?? '').toContain('no-store');
  expect(me.headers()['pragma'] ?? '').toContain('no-cache');
});
