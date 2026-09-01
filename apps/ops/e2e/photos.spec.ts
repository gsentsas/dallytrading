import { expect, test, type Page } from '@playwright/test';

/**
 * Photographier une preuve, la relire, la retirer.
 *
 * Ce que ce parcours prouve et qu'aucun test unitaire ne peut prouver : que
 * l'image franchit réellement la chaîne — navigateur, BFF, session Odoo,
 * pièce jointe privée — et revient s'afficher. Le contrôle décisif est
 * `naturalWidth` : une balise présente ne dit rien, une image décodée par le
 * navigateur dit que les octets sont arrivés.
 *
 * Aucune adresse de stockage n'est fabriquée ici. La photo se lit par le lien
 * que l'écran a lui-même posé, et par lui seul.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT_CONNU = '+221 77 123 45 67';

/** Un vrai JPEG de 48 × 32, produit par un encodeur. */
const JPEG = Buffer.from(
  '/9j/4AAQSkZJRgABAQAAAAAAAAD/2wBDACgcHiMeGSgjISMtKygwPGRBPDc3PHtYXUlkkYCZlo'
  + '+AjIqgtObDoKrarYqMyP/L2u71////m8H////6/+b9//j/2wBDASstLTw1PHZBQXb4pYyl+Pj4'
  + '+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj/wAARCAAgADAD'
  + 'ASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QA'
  + 'FgEBAQEAAAAAAAAAAAAAAAAAAAIE/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8A'
  + 'kANiQAAAAAAAAAH/2Q==',
  'base64');

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
  await page.getByLabel('Poids exact total (kg)').fill('13.5');
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();

  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const reference = await page.getByTestId('intake-enregistre')
    .locator('.reference').textContent();
  return (reference ?? '').trim();
}

async function ouvrirLeDossier(page: Page, reference: string) {
  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await expect(page.getByRole('heading', { name: /^DOSSIER A\d{3}$/ })).toBeVisible();
  await expect(page.getByTestId('photos-dossier')).toBeVisible();
}

async function envoyerUnePhoto(page: Page, nature: string) {
  await page.getByTestId('photo-appareil').setInputFiles({
    name: 'colis.jpg', mimeType: 'image/jpeg', buffer: JPEG,
  });
  // L'aperçu apparaît avant tout envoi : l'opérateur voit ce qu'il envoie.
  await expect(page.getByTestId('apercu-photo')).toBeVisible();
  await page.getByTestId('choix-nature').selectOption(nature);
  await page.getByRole('button', { name: 'ENVOYER LA PHOTO' }).click();
  await expect(page.getByTestId('photo')).toHaveCount(1);
}

/** Une image réellement décodée par le navigateur, et non une simple balise. */
async function imageChargee(page: Page): Promise<boolean> {
  return page.getByTestId('photo').locator('img').first().evaluate(
    (element) => (element as HTMLImageElement).naturalWidth > 0);
}

test('une preuve est envoyée, relue après rechargement, et attribuée',
  async ({ page }) => {
    const reference = await creerUnDossier(page);
    await ouvrirLeDossier(page, reference);
    await expect(page.getByTestId('aucune-photo')).toBeVisible();

    await envoyerUnePhoto(page, 'reception');

    // L'aperçu local a disparu : la photo affichée vient désormais du serveur.
    await expect(page.getByTestId('apercu-photo')).toHaveCount(0);
    await expect(page.getByTestId('photo-nature')).toHaveText('État à la réception');
    await expect(page.getByTestId('photo-auteur')).toHaveText('Gilles');
    await expect(page.getByTestId('photo-date')).toHaveText(
      /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
    expect(await imageChargee(page)).toBe(true);

    // Rechargement : rien ne vit dans la page, tout vient d'Odoo.
    await page.reload();
    await expect(page.getByTestId('photo')).toHaveCount(1);
    await expect(page.getByTestId('photo-nature')).toHaveText('État à la réception');
    expect(await imageChargee(page)).toBe(true);

    // Et l'écran n'a fabriqué aucune adresse de stockage.
    const source = await page.getByTestId('photo').locator('img').first()
      .getAttribute('src');
    expect(source).toContain(`/api/intakes/${encodeURIComponent(reference)}/photos/`);
    expect(source).not.toContain('/web/content');
  });

test('une preuve retirée disparaît, et ne revient pas au rechargement',
  async ({ page }) => {
    const reference = await creerUnDossier(page);
    await ouvrirLeDossier(page, reference);
    await envoyerUnePhoto(page, 'package');

    await page.getByRole('button', { name: 'RETIRER CETTE PHOTO' }).click();
    await expect(page.getByTestId('photo')).toHaveCount(0);
    await expect(page.getByTestId('aucune-photo')).toBeVisible();

    await page.reload();
    await expect(page.getByTestId('photo')).toHaveCount(0);
    await expect(page.getByTestId('aucune-photo')).toBeVisible();
  });
