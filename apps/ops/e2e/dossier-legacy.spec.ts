import { expect, test, type Page } from '@playwright/test';

/**
 * Consulter un dossier repris, et ne rien pouvoir y faire.
 *
 * Ce que ce parcours prouve et qu'aucun test unitaire ne peut prouver : que la
 * chaîne entière — navigateur, BFF, session Odoo, service en lecture seule —
 * ouvre un dossier que Dally Ops n'a pas créé, et que l'écran obtenu ne
 * propose **aucune** action.
 *
 * Le contrôle décisif est le dernier : aucune requête d'écriture ne part
 * pendant toute la visite. Un bouton absent se vérifie à l'œil ; une requête
 * absente se vérifie au réseau.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

/** Le dossier repris créé par la fixture de banc. */
const REFERENCE = process.env.OPS_E2E_LEGACY_REFERENCE ?? 'LEGACY-E2E-001';

async function ouvrirLAccueil(page: Page) {
  await page.goto('/');
  if (/\/connexion$/.test(page.url())) {
    await page.getByLabel('Identifiant').fill(OPERATEUR.login);
    await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
    await page.getByRole('button', { name: 'Se connecter' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

test('un dossier repris se consulte, et rien ne s’y écrit', async ({ page }) => {
  // Toute requête d'écriture partant de cette page est un échec du parcours.
  const ecritures: string[] = [];
  page.on('request', (requete) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(requete.method())) {
      ecritures.push(`${requete.method()} ${new URL(requete.url()).pathname}`);
    }
  });

  await ouvrirLAccueil(page);

  await page.getByRole('link', { name: /Rechercher un dossier/ }).click();
  await expect(
    page.getByRole('heading', { name: 'RECHERCHER UN DOSSIER' })).toBeVisible();
  await page.getByLabel('Nom, téléphone ou référence').fill(REFERENCE);

  const carte = page.locator('[data-test="dossier-lecture-seule"]').first();
  await expect(carte).toBeVisible();
  await expect(carte).toContainText('Lecture seule');

  // Les écritures faites pendant la connexion et la recherche ne concernent
  // pas la fiche : on repart d'une ardoise propre avant de l'ouvrir.
  ecritures.length = 0;

  await carte.click();
  await expect(page).toHaveURL(new RegExp(`/lecture-seule$`));

  await expect(page.getByTestId('fiche-lecture-seule')).toBeVisible();
  await expect(page.getByTestId('bandeau-lecture-seule'))
    .toHaveText('DOSSIER EN LECTURE SEULE');
  await expect(page.getByTestId('ls-reference')).toHaveText(REFERENCE);
  await expect(page.getByTestId('ls-client-nom')).not.toBeEmpty();

  // Aucune action : ni bouton, ni champ, ni formulaire.
  await expect(page.locator('main button')).toHaveCount(0);
  await expect(page.locator('main form')).toHaveCount(0);
  await expect(page.locator('main input, main select, main textarea'))
    .toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId('fiche-lecture-seule')).toBeVisible();

  await page.getByRole('link', { name: '← Recherche' }).click();
  await expect(page).toHaveURL(/\/recherche$/);

  // Le contrôle décisif : la visite n'a produit aucune écriture.
  expect(ecritures, 'aucune requête d’écriture ne doit partir').toEqual([]);
});
