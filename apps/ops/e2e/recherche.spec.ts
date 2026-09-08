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

  // Sur un téléphone, « Effacer » passe SOUS le champ et prend toute la
  // largeur. C'est la mise en page prévue par la feuille au palier 430px, et
  // elle ne pouvait pas s'appliquer tant qu'un `display: flex` en ligne tenait
  // la rangée : le bouton restait collé au champ et le comprimait.
  const largeur = page.viewportSize()!.width;
  expect(largeur).toBeLessThanOrEqual(430);
  expect(cadreBouton!.y).toBeGreaterThan(cadreChamp!.y);
  expect(cadreBouton!.width).toBeGreaterThan(largeur * 0.7);

  // Ce que le défaut de production écrasait : le champ garde sa largeur. Il
  // n'est plus réduit à la croix de `type="search"`.
  expect(cadreChamp!.width).toBeGreaterThan(largeur * 0.6);

  // Et rien ne déborde horizontalement.
  const debordement = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(debordement).toBeLessThanOrEqual(0);
});

test('au-delà du palier mobile, le champ domine la rangée', async ({ page }) => {
  // L'autre moitié du contrat, celle que le défaut de production inversait :
  // dès qu'il y a la place, les deux commandes partagent la ligne et le champ
  // prend tout l'espace restant. `globals.css` impose `width: 100%` à tout
  // input ET à tout button ; sans la grille, les deux se disputaient la
  // largeur et Chrome Android donnait la ligne au bouton.
  await page.setViewportSize({ width: 600, height: 900 });
  await seConnecter(page);
  await page.goto('/recherche');

  const champ = page.getByLabel('Nom, téléphone ou référence');
  const bouton = page.getByRole('button', { name: 'Effacer' });
  const cadreChamp = await champ.boundingBox();
  const cadreBouton = await bouton.boundingBox();

  expect(cadreChamp!.width).toBeGreaterThan(cadreBouton!.width * 2);
  expect(Math.abs(cadreChamp!.y - cadreBouton!.y)).toBeLessThanOrEqual(1);
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
