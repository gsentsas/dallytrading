/**
 * Comptes et utilitaires partagés par la suite E2E.
 *
 * Les identifiants viennent de l'environnement : les écrire ici les mettrait
 * dans Git, et un mot de passe committé finit toujours par être réutilisé
 * ailleurs.
 */

import type { APIRequestContext, Page } from '@playwright/test';

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} est requis pour la suite E2E (voir docs/PORTAL.md).`);
  }
  return value;
}

export const accounts = {
  portalA: { login: () => required('E2E_A_LOGIN'), password: () => required('E2E_A_PASSWORD') },
  portalB: { login: () => required('E2E_B_LOGIN'), password: () => required('E2E_B_PASSWORD') },
  staff: { login: () => required('E2E_STAFF_LOGIN'), password: () => required('E2E_STAFF_PASSWORD') },
};

export const PORTAL_COOKIE = 'dt_portal_session';

/** Connexion par l'interface réelle : formulaire, clic, navigation. */
export async function loginThroughUi(
  page: Page,
  account: { login: () => string; password: () => string },
  next?: string,
): Promise<void> {
  await page.goto(next ? `/connexion?next=${next}` : '/connexion');
  await page.getByLabel(/Adresse e-mail/i).fill(account.login());
  await page.getByLabel(/Mot de passe/i).fill(account.password());
  await page.getByRole('button', { name: /Se connecter/i }).click();
}

/**
 * Attend un chemin exact.
 *
 * Un motif glob serait piégeux ici : Playwright l'applique à l'URL COMPLÈTE,
 * query string incluse. Attendre le glob « étoile-étoile slash espace-client »
 * est donc satisfait aussitôt par `/connexion?next=/espace-client`, et l'attente
 * retourne sans que rien n'ait bougé. Constaté sur le test de redirection
 * ouverte, qui passait pour de mauvaises raisons. Comparer le `pathname` retire
 * toute ambiguïté.
 */
export async function waitForPath(page: Page, pathname: string): Promise<void> {
  await page.waitForURL((url) => url.pathname === pathname, { timeout: 15_000 });
}

/** Le message d'erreur du formulaire, et lui seul. */
export function loginError(page: Page) {
  return page.locator('form p[role="alert"]');
}

/** Le cookie de session tel que le navigateur le détient réellement. */
export async function portalCookie(page: Page) {
  const cookies = await page.context().cookies();
  return cookies.find((cookie) => cookie.name === PORTAL_COOKIE);
}

/** Appel direct au BFF, hors navigation, avec l'origine attendue. */
export async function apiMe(request: APIRequestContext, baseURL: string) {
  return request.get(`${baseURL}/api/portal/me`, {
    headers: { origin: baseURL },
  });
}
