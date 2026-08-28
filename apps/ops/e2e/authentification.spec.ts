import { expect, test } from '@playwright/test';

/**
 * La chaîne complète, de bout en bout.
 *
 * Navigateur → BFF Next.js → session Odoo → /api/v1/ops/me → « Bonjour Gilles ».
 * Rien n'est simulé : le serveur interrogé est un vrai Odoo de banc, avec un
 * compte non interne dont l'unique droit est le rôle Ops.
 */

/**
 * Comptes de banc, sur une base jetable (`dally_ops`). Ils n'existent pas en
 * production et n'y existeront pas : le mot de passe est surchargeable par
 * l'environnement pour que rien n'oblige à écrire un identifiant réel ici.
 */
const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};
const TEMOIN = {
  login: process.env.OPS_E2E_TEMOIN_LOGIN ?? 'temoin.banc',
  password: process.env.OPS_E2E_TEMOIN_PASSWORD ?? 'banc-temoin-2026',
};

/**
 * Le message d'erreur du formulaire.
 *
 * Ciblé par son élément et non par `getByRole('alert')` seul : Next place son
 * propre annonceur de route sous ce rôle, et une correspondance large
 * rendrait le test dépendant du framework plutôt que de la page.
 */
function messageErreur(page: import('@playwright/test').Page) {
  return page.locator('p[role="alert"]');
}

async function seConnecter(
  page: import('@playwright/test').Page,
  compte: { login: string; password: string },
) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(compte.login);
  await page.getByLabel('Mot de passe').fill(compte.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
}

test('un visiteur anonyme est renvoyé vers la page de connexion', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/connexion$/);
  await expect(page.getByRole('button', { name: 'Se connecter' })).toBeVisible();
});

test('un opérateur habilité arrive sur « Bonjour Gilles »', async ({ page }) => {
  await seConnecter(page, OPERATEUR);
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
  // Le nom vient d'Odoo, relu à l'instant, et non du formulaire ni du cookie.
  await expect(page.getByText('Caisse : Gilles')).toBeVisible();
});

test('l’accueil n’ouvre que les opérations autorisées', async ({ page }) => {
  await seConnecter(page, OPERATEUR);
  // Le rôle « logisticien » accorde la réception et l'encaissement, rien de plus.
  await expect(page.getByText('Réception de colis')).toBeVisible();
  await expect(page.getByText('Encaissement')).toBeVisible();
  await expect(page.getByText('Supervision')).toHaveCount(0);
  await expect(page.getByText('Transfert de caisse')).toHaveCount(0);
});

test('un compte Odoo valide mais sans rôle Ops est refusé', async ({ page }) => {
  await seConnecter(page, TEMOIN);
  await expect(messageErreur(page)).toHaveText('Identifiants invalides.');
  await expect(page).toHaveURL(/\/connexion$/);
});

test('un mot de passe faux donne exactement le même message', async ({ page }) => {
  await seConnecter(page, { login: OPERATEUR.login, password: 'mauvais-mot-de-passe' });
  await expect(messageErreur(page)).toHaveText('Identifiants invalides.');
});

test('le cookie de session est inaccessible au JavaScript de la page', async ({ page }) => {
  await seConnecter(page, OPERATEUR);
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
  // httpOnly : une XSS ne peut pas exfiltrer la session.
  const visibleDepuisLaPage = await page.evaluate(() => document.cookie);
  expect(visibleDepuisLaPage).not.toContain('dt_ops_session');
});

test('aucune session Odoo ni secret ne descend dans la page', async ({ page }) => {
  await seConnecter(page, OPERATEUR);
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
  const html = await page.content();
  for (const interdit of ['session_id=', 'OPS_SESSION_SECRET', 'API_KEY', 'freight:']) {
    expect(html).not.toContain(interdit);
  }
});

test('la déconnexion ramène à la page de connexion et ferme la session', async ({ page }) => {
  await seConnecter(page, OPERATEUR);
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
  await page.getByRole('button', { name: 'Se déconnecter' }).click();
  await expect(page).toHaveURL(/\/connexion$/);
  // Le retour en arrière ne doit pas rouvrir l'accueil.
  await page.goto('/');
  await expect(page).toHaveURL(/\/connexion$/);
});

test('GET /api/me interroge Odoo et refuse sans session', async ({ page, request }) => {
  const anonyme = await request.get('/api/me');
  expect(anonyme.status()).toBe(401);

  await seConnecter(page, OPERATEUR);
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
  const connecte = await page.request.get('/api/me');
  expect(connecte.status()).toBe(200);
  const charge = (await connecte.json()) as { data: { user: { name: string } } };
  expect(charge.data.user.name).toBe('Gilles');
});
