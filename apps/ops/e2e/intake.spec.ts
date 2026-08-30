import { expect, test, type Page } from '@playwright/test';

/**
 * La réception d'un colis, du téléphone jusqu'au dossier numéroté.
 *
 * C'est le parcours complet : le logisticien choisit un départ, identifie son
 * client, pèse le carton, et le serveur rend un dossier portant un numéro que
 * le navigateur n'a jamais calculé.
 *
 * ## Ce que ce fichier affirme, et ce qu'il n'affirme pas
 *
 * Il affirme que la chaîne tient et que le numéro local **vient du serveur** :
 * la page ne le connaît qu'après la réponse, et deux réceptions successives
 * s'incrémentent. Il n'affirme pas que la première vaut littéralement `A001` —
 * cela dépendrait de ce que le banc contient au moment où on l'exécute, donc
 * d'un état que ce fichier ne maîtrise pas. La valeur exacte, la remise à
 * `A001` sur un autre départ et la non-consommation d'un `A002` par un rejeu
 * sont prouvées dans la suite Odoo, où la base est créée puis annulée à chaque
 * test.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT_CONNU = '+221 77 123 45 67';

/** `A001`, `A002`… — le format du numéro attribué par la consolidation. */
const NUMERO_LOCAL = /^A\d{3}$/;

/**
 * Ouvre l'accueil, en se connectant seulement si nécessaire.
 *
 * Un scénario qui enchaîne deux réceptions repasse par ici avec une session
 * déjà ouverte : `/connexion` redirige alors vers l'accueil, et attendre le
 * formulaire de connexion ferait expirer le test pour la mauvaise raison.
 */
async function ouvrirLAccueil(page: Page) {
  await page.goto('/');
  if (/\/connexion$/.test(page.url())) {
    await page.getByLabel('Identifiant').fill(OPERATEUR.login);
    await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
    await page.getByRole('button', { name: 'Se connecter' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

async function ouvrirLeFormulaireColis(page: Page) {
  await ouvrirLAccueil(page);

  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();

  await page.getByLabel('Numéro de téléphone').fill(CLIENT_CONNU);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await expect(page.getByRole('heading', { name: 'DOSSIER EN COURS' })).toBeVisible();
}

async function saisirUnColis(
  page: Page,
  valeurs: {
    categorie?: string; designation?: string; quantite?: string;
    poids?: string; famille?: string; valeur?: string; methode?: string;
  } = {},
) {
  await page.getByLabel('Catégorie').fill(valeurs.categorie ?? 'Non alimentaire');
  await page.getByLabel('Désignation').fill(valeurs.designation ?? 'Savon');
  await page.getByLabel('Quantité').fill(valeurs.quantite ?? '1');
  await page.getByLabel('Poids exact total (kg)').fill(valeurs.poids ?? '13.5');
  if (valeurs.methode) {
    await page.getByLabel('Méthode facturation').selectOption(valeurs.methode);
  }
  await page.getByLabel('Famille tarifaire').selectOption(valeurs.famille ?? 'non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill(valeurs.valeur ?? '25000');
}

/** Le numéro local affiché sur l'écran de succès. */
async function numeroAffiche(page: Page): Promise<string> {
  const titre = await page.getByTestId('intake-enregistre').locator('.succes').textContent();
  const trouve = /DOSSIER (A\d{3}) ENREGISTRÉ/.exec(titre ?? '');
  expect(trouve, `titre inattendu : ${titre}`).not.toBeNull();
  return trouve![1] as string;
}

test('le formulaire rappelle le dossier en cours', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);
  await expect(page.getByTestId('consolidation-selectionnee')).toHaveText(DEPART);

  // L'écran n'affiche ni le nom du client — la page ne l'a pas — ni son jeton
  // opaque, qui n'aiderait personne au comptoir.
  await expect(page.getByTestId('client-selectionne')).toHaveText('Client sélectionné');
  await expect(page.getByText('Aissatou Kandji')).toHaveCount(0);
});

test('les familles tarifaires viennent du serveur, sans aucun prix', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);

  const options = await page.getByLabel('Famille tarifaire').locator('option').allTextContents();
  expect(options.join(' ')).toContain('Non alimentaire');

  // Le logisticien choisit une famille, pas une règle : ni prix, ni date, ni
  // segment, ni marge ne descendent sur le téléphone.
  const html = await page.content();
  // `margin` n'est pas dans la liste : c'est une propriété CSS, et la
  // chercher ferait échouer le test sur un style en ligne.
  for (const interdit of ['price_per_kg', 'tariff_rule', 'date_from',
                          'customer_segment', 'volumetric_ratio', 'marge']) {
    expect(html).not.toContain(interdit);
  }
});

test('une réception est enregistrée et numérotée par le serveur', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);
  await saisirUnColis(page);
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();

  const carte = page.getByTestId('intake-enregistre');
  await expect(carte).toBeVisible();

  const local = await numeroAffiche(page);
  expect(local).toMatch(NUMERO_LOCAL);
  // La référence globale est composée par le serveur à partir du départ.
  await expect(carte.locator('.reference')).toHaveText(`${DEPART}-${local}`);
  await expect(carte).toContainText('1 × Savon');
  await expect(carte).toContainText('13.5 kg');
  // Règle de banc : aérien / non alimentaire à 5,00 € le kilo.
  await expect(carte).toContainText('Transport :');
  await expect(carte).toContainText('67,50');
});

test('la réception suivante prend le numéro suivant', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);
  await saisirUnColis(page, { designation: 'Bissap', poids: '10' });
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();
  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const premier = await numeroAffiche(page);

  await ouvrirLeFormulaireColis(page);
  await saisirUnColis(page, { designation: 'Miel', poids: '8' });
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();
  await expect(page.getByTestId('intake-enregistre')).toBeVisible();
  const second = await numeroAffiche(page);

  // Le navigateur n'a jamais calculé ces numéros : il les a reçus.
  expect(Number(second.slice(1))).toBe(Number(premier.slice(1)) + 1);
});

test('« sur devis » reste une réception valide', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);
  await saisirUnColis(page, { designation: 'Pièce détachée', methode: 'quote' });
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();

  const carte = page.getByTestId('intake-enregistre');
  await expect(carte).toBeVisible();
  await expect(carte).toContainText('Sur devis');
  // Une grille commerciale manquante n'empêche pas de recevoir le colis.
  await expect(carte).not.toContainText('0,00');
});

test('un poids nul est refusé sans atteindre le serveur', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);

  const envois: string[] = [];
  page.on('request', (requete) => {
    if (requete.url().includes('/api/intakes') && requete.method() === 'POST') {
      envois.push(requete.url());
    }
  });

  await saisirUnColis(page, { poids: '0' });
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();
  await expect(page.locator('p[role="alert"]')).toBeVisible();
  expect(envois).toHaveLength(0);
});

test('une valeur déclarée absente est refusée', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);
  await saisirUnColis(page, { valeur: '0' });
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();
  await expect(page.locator('p[role="alert"]')).toBeVisible();
  await expect(page.getByTestId('intake-enregistre')).toHaveCount(0);
});

test('aucun identifiant Odoo ni secret ne descend dans la page', async ({ page }) => {
  await ouvrirLeFormulaireColis(page);
  await saisirUnColis(page, { designation: 'Habits' });
  await page.getByRole('button', { name: 'Enregistrer la réception' }).click();
  await expect(page.getByTestId('intake-enregistre')).toBeVisible();

  const html = await page.content();
  for (const interdit of ['shipment_id', 'package_id', 'partner_id', 'consolidation_id',
                          'tariff_rule_id', 'collection_sequence', 'sync_source_key',
                          'external_line_key', 'sale_order_id', 'invoice_id',
                          'session_id=', 'API_KEY', 'freight:']) {
    expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
  }
});

test('un visiteur anonyme ne peut ni voir la page ni appeler la route', async ({ page, request }) => {
  await page.goto(`/reception/colis?consolidation=${DEPART}&customer=00000000-0000-4000-8000-000000000000`);
  await expect(page).toHaveURL(/\/connexion$/);

  const anonyme = await request.post('/api/intakes', {
    headers: { 'Content-Type': 'application/json' },
    data: { request_uuid: '11111111-2222-4333-8444-555555555555' },
  });
  expect(anonyme.status()).toBe(401);

  const familles = await request.get('/api/tariff-families');
  expect(familles.status()).toBe(401);
});
