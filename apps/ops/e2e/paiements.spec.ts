import { expect, test, type Page } from '@playwright/test';

/**
 * Encaisser au comptoir, jusque dans la base.
 *
 * Le parcours crée un dossier, enregistre un paiement Wave en francs, et
 * vérifie que l'écran annonce l'encaissement sans prétendre qu'il est
 * comptabilisé — la facture n'existe pas encore, et c'est le cas normal.
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

test('un dossier neuf n’a aucun paiement', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);
  await expect(page.getByTestId('aucun-paiement')).toBeVisible();
});

test('le collecteur est affiché mais non modifiable', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);
  await page.getByRole('button', { name: '+ ENREGISTRER UN PAIEMENT' }).click();

  await expect(page.getByTestId('collecteur')).toHaveText('Gilles');
  // Le collecteur vient d'une correspondance configurée, pas d'une saisie.
  await expect(page.locator('input[name="collector"]')).toHaveCount(0);
  await expect(page.locator('input[name="collected_by"]')).toHaveCount(0);
});

test('un encaissement Wave est enregistré et annoncé en attente', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  await page.getByRole('button', { name: '+ ENREGISTRER UN PAIEMENT' }).click();
  await page.getByLabel('Mode de paiement').selectOption('wave|XOF');
  await page.getByLabel('Montant').fill('44280');
  await page.getByRole('button', { name: 'CONFIRMER L’ENCAISSEMENT' }).click();

  await expect(page.getByTestId('paiement')).toHaveCount(1);
  await expect(page.getByTestId('paiement')).toContainText('44 280');
  await expect(page.getByTestId('paiement')).toContainText('Wave');
  await expect(page.getByTestId('paiement')).toContainText('Gilles');
  // Aucune facture postée : c'est le cas normal, pas une alerte.
  await expect(page.getByTestId('paiement')).toContainText('En attente de facturation');
});

test('deux encaissements coexistent et se totalisent par devise', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  for (const [mode, montant] of [['wave|XOF', '30000'], ['cash|EUR', '50']] as const) {
    await page.getByRole('button', { name: '+ ENREGISTRER UN PAIEMENT' }).click();
    await page.getByLabel('Mode de paiement').selectOption(mode);
    await page.getByLabel('Montant').fill(montant);
    await page.getByRole('button', { name: 'CONFIRMER L’ENCAISSEMENT' }).click();
    await expect(page.getByTestId('formulaire-paiement')).toHaveCount(0);
  }

  await expect(page.getByTestId('paiement')).toHaveCount(2);
  // Deux devises, deux totaux : aucune conversion n'est faite.
  const resume = page.getByTestId('resume-paiements');
  await expect(resume).toContainText('30 000');
  await expect(resume).toContainText('50,00');
});

test('un montant nul est refusé sans atteindre le serveur', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);

  const envois: string[] = [];
  page.on('request', (requete) => {
    if (requete.url().includes('/payments') && requete.method() === 'POST') {
      envois.push(requete.url());
    }
  });

  await page.getByRole('button', { name: '+ ENREGISTRER UN PAIEMENT' }).click();
  await page.getByLabel('Montant').fill('0');
  await page.getByRole('button', { name: 'CONFIRMER L’ENCAISSEMENT' }).click();
  await expect(page.locator('p[role="alert"]')).toBeVisible();
  expect(envois).toHaveLength(0);
});

test('le terrain peut terminer sans encaisser', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);
  await expect(page.getByTestId('aucun-paiement')).toBeVisible();
  await page.getByRole('button', { name: 'TERMINER LA SAISIE' }).click();
  // Le dossier reste parfaitement valide sans paiement.
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
});

test('aucune donnée comptable ne descend dans la page', async ({ page }) => {
  const reference = await creerUnDossier(page);
  await ouvrirLeDossier(page, reference);
  await page.getByRole('button', { name: '+ ENREGISTRER UN PAIEMENT' }).click();
  await page.getByLabel('Montant').fill('1000');
  await page.getByRole('button', { name: 'CONFIRMER L’ENCAISSEMENT' }).click();
  await expect(page.getByTestId('paiement')).toHaveCount(1);

  const html = (await page.content()).toLowerCase();
  for (const interdit of ['journal_id', 'payment_method_line', 'account_payment',
                          'invoice_id', 'collection_id', 'external_payment_key',
                          'error_message']) {
    expect(html).not.toContain(interdit.toLowerCase());
  }
  // La clé de source Ops se cherche à sa forme réelle, `ops:<uuid>`, et non par
  // la sous-chaîne « ops: » : celle-ci apparaît dans les références de
  // déduplication React Flight de Next (`$4:props:children:…`), où elle n'est
  // que la fin de « props: ». Le test signalait une fuite là où il n'y en a pas.
  expect(html).not.toMatch(/ops:[0-9a-f]{8}/);
});

test('un encaissement autonome part de l’accueil et retrouve le dossier par la recherche',
  async ({ page }) => {
    // Ce que ce test protège : qu'un opérateur venu encaisser n'ait pas à
    // simuler une réception pour atteindre la fiche. Le dossier créé ici n'est
    // qu'un décor ; la démonstration commence au retour à l'accueil.
    const reference = await creerUnDossier(page);

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();

    // À partir d'ici, aucune URL de dossier n'est fabriquée par le test. Si
    // l'une des étapes manque, le parcours s'arrête — et c'est bien ce qu'on
    // veut mesurer : l'autonomie du chemin, pas la joignabilité de la fiche.
    await page.getByRole('link', { name: /Encaissement/ }).click();
    await expect(page).toHaveURL(/\/recherche$/);

    await page.getByLabel('Nom, téléphone ou référence').fill(reference);
    const resultat = page.locator('[data-test="dossier-ouvrable"]').first();
    await expect(resultat).toBeVisible();
    await resultat.click();

    await expect(page.getByRole('heading', { name: /^DOSSIER A\d{3}$/ })).toBeVisible();

    await page.getByRole('button', { name: '+ ENREGISTRER UN PAIEMENT' }).click();
    await page.getByLabel('Mode de paiement').selectOption('cash|EUR');
    await page.getByLabel('Montant').fill('75');
    await page.getByRole('button', { name: 'CONFIRMER L’ENCAISSEMENT' }).click();

    await expect(page.getByTestId('paiement')).toHaveCount(1);
    await expect(page.getByTestId('paiement')).toContainText('75,00');
    await expect(page.getByTestId('paiement')).toContainText('Gilles');
  });

test('un visiteur anonyme n’atteint pas les routes de paiement', async ({ request }) => {
  const canaux = await request.get('/api/payment-channels');
  expect(canaux.status()).toBe(401);

  const paiement = await request.post('/api/intakes/AIR-DSS-CDG-TEST-001-A001/payments', {
    headers: { 'Content-Type': 'application/json' },
    data: { request_uuid: '11111111-2222-4333-8444-555555555555' },
  });
  expect(paiement.status()).toBe(401);
});
