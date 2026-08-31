import { expect, test, type Page } from '@playwright/test';

/**
 * Retrouver un dossier au comptoir, puis l'ouvrir.
 *
 * Le seul écran de Dally Ops dont le point de départ est ce que le client dit.
 * Ce que les assertions protègent : la navigation passe par la référence
 * globale — jamais par `A001`, qui appartient à son départ — et une frappe
 * unique n'interroge pas le serveur.
 */

const GILLES = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

async function seConnecter(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(GILLES.login);
  await page.getByLabel('Mot de passe').fill(GILLES.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: /^Bonjour / })).toBeVisible();
}

test('l’accueil ouvre la recherche', async ({ page }) => {
  await seConnecter(page);
  await page.getByRole('link', { name: /Rechercher un dossier/ }).click();
  await expect(page).toHaveURL(/\/recherche$/);
  await expect(page.getByRole('heading', { name: 'RECHERCHER UN DOSSIER' })).toBeVisible();
});

test('un dossier se retrouve et s’ouvre par sa référence globale', async ({ page }) => {
  await seConnecter(page);
  await page.goto('/recherche');

  const champ = page.getByLabel('Nom, téléphone ou référence');
  await expect(champ).toBeFocused();

  // Une frappe unique n'interroge pas le serveur : l'invite reste affichée.
  await champ.fill('A');
  await expect(page.getByText('Tapez au moins deux caractères')).toBeVisible();

  await champ.fill('A0');
  const premier = page.locator('[data-test="dossier-ouvrable"]').first();
  await expect(premier).toBeVisible();

  const cible = await premier.getAttribute('href');
  expect(cible).toBeTruthy();
  // La référence locale ne compose jamais une URL : deux départs ont chacun
  // leur `A001`, et l'un ouvrirait le dossier de l'autre.
  expect(cible).not.toMatch(/\/reception\/dossier\/A\d+$/);

  await premier.click();
  await expect(page.getByRole('heading', { name: /^DOSSIER / })).toBeVisible();
});

test('le bouton effacer rend la main au champ', async ({ page }) => {
  await seConnecter(page);
  await page.goto('/recherche');
  const champ = page.getByLabel('Nom, téléphone ou référence');
  await champ.fill('Soumar');
  await page.getByRole('button', { name: 'Effacer' }).click();
  await expect(champ).toHaveValue('');
  await expect(champ).toBeFocused();
});
