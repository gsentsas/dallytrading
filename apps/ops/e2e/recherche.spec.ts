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

test('la barre de recherche reste utilisable sur un écran de téléphone', async ({ page }) => {
  // Le seul contrôle qui mesure vraiment : les styles en ligne se vérifient
  // au rendu, mais une largeur ne se prouve qu'à l'écran. Le viewport est
  // celui de la configuration Playwright — un téléphone, pas un bureau.
  await seConnecter(page);
  await page.goto('/recherche');

  const champ = page.getByLabel('Nom, téléphone ou référence');
  const bouton = page.getByRole('button', { name: 'Effacer' });
  await expect(champ).toBeVisible();
  await expect(bouton).toBeVisible();

  const cadreChamp = await champ.boundingBox();
  const cadreBouton = await bouton.boundingBox();
  expect(cadreChamp).not.toBeNull();
  expect(cadreBouton).not.toBeNull();

  // Le champ doit dominer la rangée, pas la partager : c'est exactement ce
  // que le défaut de production inversait.
  expect(cadreChamp!.width).toBeGreaterThan(cadreBouton!.width * 2);

  // Les deux commandes tiennent sur la même ligne, à la même hauteur.
  expect(Math.abs(cadreChamp!.y - cadreBouton!.y)).toBeLessThanOrEqual(1);

  // Et rien ne déborde horizontalement.
  const debordement = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(debordement).toBeLessThanOrEqual(0);
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
