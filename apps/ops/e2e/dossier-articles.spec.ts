import { expect, test, type Page } from '@playwright/test';

/**
 * Un dossier à plusieurs articles, du téléphone jusqu'à la base.
 *
 * Le parcours crée un dossier, lui ajoute un second article, corrige le
 * premier, et vérifie que les totaux affichés viennent bien du serveur. Le
 * dernier scénario joue la course entre deux écrans : celui qui écrit avec une
 * version périmée est refusé.
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

/** Crée un dossier d'une ligne et rend sa référence. */
async function creerUnDossier(page: Page, designation = 'Savon'): Promise<string> {
  await ouvrirLAccueil(page);
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT_CONNU);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill(designation);
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
}

async function remplirArticle(
  page: Page,
  valeurs: { designation: string; poids: string; quantite?: string },
) {
  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill(valeurs.designation);
  await page.getByLabel('Quantité').fill(valeurs.quantite ?? '1');
  await page.getByLabel('Poids exact total (kg)').fill(valeurs.poids);
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
}

test('le dossier affiche son article et ses totaux', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  await expect(page.getByTestId('article')).toHaveCount(1);
  await expect(page.getByText('Aissatou Kandji')).toBeVisible();
  await expect(page.getByTestId('totaux')).toContainText('1 article(s)');
  await expect(page.getByTestId('totaux')).toContainText('67,50');
});

test('un second article rejoint le même dossier', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  await page.getByRole('button', { name: '+ AJOUTER UN ARTICLE' }).click();
  await remplirArticle(page, { designation: 'Bissap', poids: '8' });
  await page.getByRole('button', { name: 'ENREGISTRER L’ARTICLE' }).click();

  await expect(page.getByTestId('article')).toHaveCount(2);
  await expect(page.getByText('Bissap')).toBeVisible();
  // Le dossier n'a pas changé de numéro : aucun A002 créé.
  await expect(page.getByTestId('totaux')).toContainText('2 article(s)');
  await expect(page.getByTestId('totaux')).toContainText('21,50 kg');
});

test('une correction de poids met à jour les totaux du serveur', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  await page.getByRole('button', { name: 'MODIFIER' }).first().click();
  await page.getByLabel('Poids exact total (kg)').fill('14');
  await page.getByRole('button', { name: 'ENREGISTRER LES CORRECTIONS' }).click();

  await expect(page.getByTestId('article')).toHaveCount(1);
  await expect(page.getByTestId('totaux')).toContainText('14,00 kg');
  // 14 kg × 5,00 € : le prix vient d'Odoo, pas d'un calcul local.
  await expect(page.getByTestId('totaux')).toContainText('70,00');
});

test('annuler une correction ne change rien', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  await page.getByRole('button', { name: 'MODIFIER' }).first().click();
  await page.getByLabel('Poids exact total (kg)').fill('99');
  await page.getByRole('button', { name: 'ANNULER' }).click();

  await expect(page.getByTestId('totaux')).toContainText('13,50 kg');
});

test('une version périmée est refusée sans rien écraser', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  const detail = await page.request.get(
    `/api/intakes/${encodeURIComponent(reference)}`);
  const dossier = (await detail.json()).data.intake;
  const ligne = dossier.lines[0];

  const corps = (poids: number) => ({
    request_uuid: crypto.randomUUID(),
    expected_revision: ligne.revision,
    line: {
      line_uuid: ligne.reference, package_type: 'parcel',
      goods_category: ligne.goods_category, description: ligne.description,
      quantity: ligne.quantity, announced_weight_kg: null,
      exact_weight_kg: poids, length_cm: null, width_cm: null, height_cm: null,
      billing_method: 'real', tariff_family_code: ligne.tariff_family_code,
      customs_value_xof: ligne.customs_value_xof,
    },
  });
  const url = `/api/intakes/${encodeURIComponent(reference)}`
    + `/lines/${encodeURIComponent(ligne.reference)}`;

  const premiere = await page.request.put(url, {
    headers: { 'Content-Type': 'application/json' }, data: corps(16),
  });
  expect(premiere.status()).toBe(200);

  // Le second écran écrit avec la version qu'il avait lue avant la première.
  const seconde = await page.request.put(url, {
    headers: { 'Content-Type': 'application/json' }, data: corps(12),
  });
  expect(seconde.status()).toBe(409);
  expect((await seconde.json()).code).toBe('stale_line');

  const apres = await page.request.get(
    `/api/intakes/${encodeURIComponent(reference)}`);
  expect((await apres.json()).data.intake.lines[0].exact_weight_kg).toBe(16);
});

test('aucun identifiant Odoo ne descend dans la page du dossier', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  const html = await page.content();
  for (const interdit of ['shipment_id', 'package_id', 'partner_id', 'consolidation_id',
                          'consolidation_line_id', 'tariff_rule_id', 'external_line_key',
                          'sync_source_key', 'session_id=', 'API_KEY']) {
    expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
  }
});

test('un visiteur anonyme n’atteint ni la page ni les routes', async ({ page, request }) => {
  await page.goto('/reception/dossier/AIR-DSS-CDG-TEST-001-A001');
  await expect(page).toHaveURL(/\/connexion$/);

  const detail = await request.get('/api/intakes/AIR-DSS-CDG-TEST-001-A001');
  expect(detail.status()).toBe(401);

  const ajout = await request.post('/api/intakes/AIR-DSS-CDG-TEST-001-A001/lines', {
    headers: { 'Content-Type': 'application/json' },
    data: { request_uuid: '11111111-2222-4333-8444-555555555555' },
  });
  expect(ajout.status()).toBe(401);
});
