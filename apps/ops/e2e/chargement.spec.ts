import { expect, test, type Page } from '@playwright/test';

/**
 * Préparer un départ, et vérifier que rien d'autre ne bouge.
 *
 * Ce que ce parcours prouve et qu'aucun test unitaire ne peut prouver : que le
 * geste traverse la chaîne entière — navigateur, BFF, session Odoo,
 * `dally.freight.consolidation.line` — puis survit à un rechargement, **sans**
 * que l'état du dossier ait avancé d'un mot.
 *
 * Il consigne aussi le fait le moins intuitif de l'écran : une réception
 * native arrive **déjà chargée** sur son départ prévu. Le premier geste
 * possible est donc un retrait, pas un chargement.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT_CONNU = '+221 77 123 45 67';

async function ouvrirLAccueil(page: Page) {
  await page.goto('/');
  if (/\/connexion$/.test(page.url())) {
    await page.getByLabel('Identifiant').fill(OPERATEUR.login);
    await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
    await page.getByRole('button', { name: 'Se connecter' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

async function creerUnDossier(page: Page): Promise<string> {
  await ouvrirLAccueil(page);
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT_CONNU);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill('Savon');
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill('9.5');
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();

  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const reference = await page.getByTestId('intake-enregistre')
    .locator('.reference').textContent();
  return (reference ?? '').trim();
}

test('un colis se retire puis se recharge, et l’état du dossier ne bouge pas',
  async ({ page }) => {
    const reference = await creerUnDossier(page);

    // L'état du dossier, relevé avant tout geste de chargement.
    await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
    const etatDossier = page.getByTestId('etat-libelle');
    const etatAvant = await etatDossier.textContent();

    await page.goto('/chargement');
    await page.locator('section.carte', { hasText: DEPART })
      .getByRole('link', { name: /Préparer|Consulter/ }).click();
    await expect(page.getByTestId('chargement-depart')).toBeVisible();

    const dossier = page.locator('[data-testid="dossier-chargement"]')
      .filter({ hasText: reference });
    await expect(dossier).toBeVisible();
    const colis = dossier.locator('[data-testid="colis-chargement"]').first();

    // La réception a déjà attaché le colis : le geste offert est le retrait.
    await expect(colis.getByTestId('colis-statut')).toHaveText('Chargé');
    await expect(colis.getByTestId('retirer-colis')).toBeVisible();

    await colis.getByTestId('retirer-colis').click();
    await expect(colis.getByTestId('colis-statut')).toHaveText('À charger');
    await expect(colis.getByTestId('colis-compte')).toHaveText('0 / 1');

    // Rien ne vit dans la page : tout vient d'Odoo.
    await page.reload();
    await expect(colis.getByTestId('colis-statut')).toHaveText('À charger');

    await colis.getByTestId('charger-colis').click();
    await expect(colis.getByTestId('colis-statut')).toHaveText('Chargé');
    await expect(colis.getByTestId('colis-compte')).toHaveText('1 / 1');
    await expect(dossier.getByTestId('dossier-complet')).toBeVisible();

    await page.reload();
    await expect(colis.getByTestId('colis-statut')).toHaveText('Chargé');

    // Le contrôle décisif : charger n'a pas fait avancer le dossier.
    await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
    await expect(etatDossier).toHaveText(etatAvant ?? '');
  });

test('l’écran ne propose aucun geste de workflow sur le départ',
  async ({ page }) => {
    await ouvrirLAccueil(page);
    await page.goto('/chargement');
    await page.locator('section.carte', { hasText: DEPART })
      .getByRole('link', { name: /Préparer|Consulter/ }).click();
    await expect(page.getByTestId('chargement-depart')).toBeVisible();

    // Ni clôture de collecte, ni mise au départ, ni départ : ces gestes
    // engagent le dossier maître et restent au back-office.
    for (const interdit of [/Clôturer/i, /Prêt au départ/i, /Faire partir/i,
                            /Enregistrer le départ/i]) {
      await expect(page.getByRole('button', { name: interdit })).toHaveCount(0);
    }
    // Aucune quantité au clavier.
    await expect(page.locator('[data-testid="chargement-depart"] input'))
      .toHaveCount(0);
  });
