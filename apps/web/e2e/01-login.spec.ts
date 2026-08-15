/**
 * Connexion — le chemin nominal et les trois refus.
 *
 * ## Pourquoi la suite est découpée en fichiers numérotés
 *
 * `/api/portal/auth/login` limite à 10 tentatives par IP et 5 par identifiant
 * sur 5 minutes. Une suite E2E parle depuis une seule IP : exécutée d'un bloc,
 * elle se freine elle-même et échoue en 429.
 *
 * La limite n'est PAS relâchée pour autant. Chaque fichier reste sous le seuil,
 * et le lanceur redémarre l'instance Next de test entre les fichiers — ce qui
 * remet à zéro un compteur qui vit en mémoire d'un seul processus. Ce détour est
 * lui-même une démonstration de la limite documentée au §7 de docs/PORTAL.md :
 * elle est réelle, et elle n'est pas distribuée.
 *
 * Budget de ce fichier : 6 tentatives.
 */

import { expect, test, type Page } from '@playwright/test';

import {
  accounts,
  loginError,
  loginThroughUi,
  portalCookie,
  waitForPath,
} from './fixtures';

test('Portal A se connecte et voit sa propre identité', async ({ page }) => {
  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  // Le titre est celui du tableau de bord ; l'identité est dans l'en-tête de
  // navigation, rendu par le layout du portail.
  await expect(page.getByRole('heading', { name: 'Tableau de bord' })).toBeVisible();
  await expect(page.getByText(/E2E Contact A/i).first()).toBeVisible();
  await expect(page.getByText(/E2E Alpha SARL/i).first()).toBeVisible();
});

test('le mot de passe ne circule jamais par l’URL', async ({ page }) => {
  const urls: string[] = [];
  page.on('request', (request) => urls.push(request.url()));

  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  expect(urls.length).toBeGreaterThan(0);
  for (const url of urls) {
    expect(url).not.toContain(accounts.portalA.password());
    expect(url.toLowerCase()).not.toContain('password');
  }
});

/**
 * Une tentative, et tout ce qu'elle permet d'observer de l'extérieur.
 *
 * C'est cette fonction qui rend le test « indistinguable » honnête : elle capture
 * exactement ce qu'un attaquant peut voir — statut, corps, message, cookie, URL —
 * et rien de plus.
 */
async function attempt(page: Page, login: string, password: string) {
  await page.goto('/connexion');
  await page.getByLabel(/Adresse e-mail/i).fill(login);
  await page.getByLabel(/Mot de passe/i).fill(password);

  const pending = page.waitForResponse((r) => r.url().includes('/api/portal/auth/login'));
  const startedAt = Date.now();
  await page.getByRole('button', { name: /Se connecter/i }).click();
  const response = await pending;
  const elapsedMs = Date.now() - startedAt;

  await loginError(page).waitFor({ state: 'visible' });

  return {
    status: response.status(),
    body: await response.text(),
    message: (await loginError(page).textContent())?.trim() ?? '',
    cookie: await portalCookie(page),
    pathname: new URL(page.url()).pathname,
    elapsedMs,
  };
}

test('un compte interne est refusé et n’obtient aucun cookie', async ({ page }) => {
  const staff = await attempt(page, accounts.staff.login(), accounts.staff.password());

  expect(staff.status).toBe(401);
  expect(staff.cookie).toBeUndefined();
  expect(staff.pathname).toBe('/connexion');
});

test('mot de passe faux, compte inconnu et compte interne sont indistinguables', async ({
  page,
}) => {
  const wrongPassword = await attempt(
    page, accounts.portalA.login(), 'ce-mot-de-passe-est-faux-0000',
  );
  const unknown = await attempt(
    page, 'personne.inexistante@e2e-neant.invalid', 'ce-mot-de-passe-est-faux-0000',
  );
  const staff = await attempt(page, accounts.staff.login(), accounts.staff.password());

  expect(unknown.status).toBe(wrongPassword.status);
  expect(staff.status).toBe(wrongPassword.status);

  // Le corps ne diffère que par l'identifiant de corrélation, qui est aléatoire
  // et ne renseigne sur rien.
  const strip = (body: string) => body.replace(/"requestId":"[^"]*"/, '');
  expect(strip(unknown.body)).toBe(strip(wrongPassword.body));
  expect(strip(staff.body)).toBe(strip(wrongPassword.body));

  expect(unknown.message).toBe(wrongPassword.message);
  expect(staff.message).toBe(wrongPassword.message);

  for (const result of [wrongPassword, unknown, staff]) {
    expect(result.cookie).toBeUndefined();
    expect(result.pathname).toBe('/connexion');
  }

  /*
   * Timing — mesure grossière, assumée comme telle.
   *
   * Un compte inexistant évite le hachage du mot de passe côté Odoo, donc répond
   * plus vite. On ne prétend pas à une résistance aux attaques temporelles : on
   * vérifie seulement qu'aucun chemin n'a été rendu radicalement différent (par
   * exemple un appel réseau supplémentaire pour un cas et pas pour l'autre). Le
   * seuil est large exprès — le resserrer produirait un test instable qui
   * échouerait au gré de la charge de la machine.
   */
  const times = [wrongPassword.elapsedMs, unknown.elapsedMs, staff.elapsedMs];
  const ratio = Math.max(...times) / Math.max(1, Math.min(...times));
  expect(ratio).toBeLessThan(20);
});
