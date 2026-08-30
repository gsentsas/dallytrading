import { expect, test, type Page } from '@playwright/test';

/**
 * Déclarer une dépense de terrain, jusque dans la base.
 *
 * Le parcours vérifie deux propriétés que rien d'autre ne peut établir : que
 * l'argent sorti de la caisse survit à un envoi de photo raté, et que deux
 * devises se lisent côte à côte sans jamais être additionnées.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';

/** Une photo minimale : ce qui compte, ce sont ses premiers octets. */
const PHOTO = Buffer.concat([
  Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00]),
  Buffer.alloc(256, 0x2a),
]);

/** Une page HTML déguisée en photo : le nom ment, les octets non. */
const FAUSSE_PHOTO = Buffer.from('<html><script>alert(1)</script></html>', 'utf8');

async function ouvrirLAccueil(page: Page) {
  await page.goto('/');
  if (/\/connexion$/.test(page.url())) {
    await page.getByLabel('Identifiant').fill(OPERATEUR.login);
    await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
    await page.getByRole('button', { name: 'Se connecter' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

async function ouvrirLeDepart(page: Page) {
  await ouvrirLAccueil(page);
  await page.getByRole('link', { name: /Dépense de caisse/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await expect(page.getByRole('heading', { name: 'Dépenses du départ' })).toBeVisible();
}

/** Déclare une dépense et rend sa carte. */
async function declarer(
  page: Page,
  { nature, montant, devise = 'XOF' }: { nature: string; montant: string; devise?: string },
) {
  await page.getByRole('button', { name: 'DÉCLARER UNE DÉPENSE' }).click();
  await page.getByLabel('Nature').fill(nature);
  await page.getByLabel('Description').fill(`Dépense ${nature}`);
  await page.getByLabel('Montant', { exact: true }).fill(montant);
  await page.getByLabel('Devise').selectOption(devise);
  await page.getByRole('button', { name: 'ENREGISTRER LA DÉPENSE' }).click();
  await expect(page.getByTestId('formulaire-depense')).toHaveCount(0);
  // La fermeture du formulaire ne dit que « le client a fini d'envoyer ». Les
  // totaux, eux, viennent du serveur : les lire avant que la page ne se soit
  // rafraîchie donne l'ancien montant, et le test échoue une fois sur trois
  // sans qu'aucune dépense ne manque en base.
  const carte = page.locator('section.carte', { hasText: nature });
  await expect(carte).toBeVisible();
  return carte;
}

/** Un libellé unique par exécution : la base du banc n'est pas remise à zéro. */
function nature(): string {
  return `Manut-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4)}`;
}

/**
 * Les totaux affichés, par devise.
 *
 * La base du banc n'est pas remise à zéro entre deux exécutions : affirmer un
 * total absolu ferait passer le test la première fois et échouer la seconde.
 * On mesure donc l'écart, qui, lui, ne dépend que de ce que le scénario vient
 * de saisir.
 */
async function totaux(page: Page): Promise<Record<string, number>> {
  const section = page.getByTestId('total-depenses');
  if ((await section.count()) === 0) return {};
  const lignes = await section.locator('p.reference').allTextContents();
  const releve: Record<string, number> = {};
  for (const ligne of lignes) {
    const devise = ligne.includes('€') ? 'EUR' : 'XOF';
    releve[devise] = Number(ligne.replace(/[^\d,]/g, '').replace(',', '.'));
  }
  return releve;
}

test('le départ choisi n’est pas celui des réceptions', async ({ page }) => {
  await ouvrirLAccueil(page);
  await page.getByRole('link', { name: /Dépense de caisse/ }).click();
  await expect(page.getByRole('heading', { name: 'Déclarer une dépense' })).toBeVisible();
  // Un départ qui n'accepte plus de colis accepte encore des dépenses : la
  // liste porte donc son état, ce que celle des réceptions n'affiche pas.
  await expect(page.locator('section.carte', { hasText: DEPART })).toContainText(
    'Collecte ouverte');
});

test('une dépense déclarée porte le payeur configuré et l’état « à vérifier »',
  async ({ page }) => {
    await ouvrirLeDepart(page);
    const libelle = nature();
    const carte = await declarer(page, { nature: libelle, montant: '15000' });

    await expect(carte).toContainText('15 000');
    await expect(carte).toContainText('Espèces');
    await expect(carte).toContainText('Gilles');
    await expect(carte).toContainText('À vérifier');
  });

test('le payeur est affiché mais non modifiable', async ({ page }) => {
  await ouvrirLeDepart(page);
  await page.getByRole('button', { name: 'DÉCLARER UNE DÉPENSE' }).click();

  await expect(page.getByTestId('payeur')).toHaveText('Gilles');
  // Le payeur vient d'une correspondance configurée, jamais d'une saisie.
  await expect(page.locator('input[name="actor_name"]')).toHaveCount(0);
  await expect(page.locator('input[name="paid_by"]')).toHaveCount(0);
});

test('deux devises se totalisent séparément, sans conversion', async ({ page }) => {
  await ouvrirLeDepart(page);
  const avant = await totaux(page);
  await declarer(page, { nature: nature(), montant: '10000', devise: 'XOF' });
  await declarer(page, { nature: nature(), montant: '25', devise: 'EUR' });
  const apres = await totaux(page);

  // Deux totaux, jamais un seul : convertir demanderait un taux, et aucun
  // taux n'est appliqué nulle part dans la chaîne.
  expect(Object.keys(apres).sort()).toEqual(['EUR', 'XOF']);
  expect((apres.XOF ?? 0) - (avant.XOF ?? 0)).toBe(10000);
  expect((apres.EUR ?? 0) - (avant.EUR ?? 0)).toBe(25);
});

test('un montant nul est refusé sans atteindre le serveur', async ({ page }) => {
  await ouvrirLeDepart(page);
  const envois: string[] = [];
  page.on('request', (requete) => {
    if (requete.url().includes('/api/expenses') && requete.method() === 'POST') {
      envois.push(requete.url());
    }
  });

  await page.getByRole('button', { name: 'DÉCLARER UNE DÉPENSE' }).click();
  await page.getByLabel('Nature').fill('Essai');
  await page.getByLabel('Description').fill('Essai');
  await page.getByLabel('Montant', { exact: true }).fill('0');
  await page.getByRole('button', { name: 'ENREGISTRER LA DÉPENSE' }).click();

  await expect(page.locator('p[role="alert"]')).toBeVisible();
  expect(envois).toHaveLength(0);
});

test('une photo de ticket se joint après coup', async ({ page }) => {
  await ouvrirLeDepart(page);
  const libelle = nature();
  const carte = await declarer(page, { nature: libelle, montant: '7500' });

  await carte.getByRole('button', { name: 'AJOUTER LA PHOTO' }).click();
  await page.getByLabel('Photo du ticket').setInputFiles({
    name: 'ticket.jpg', mimeType: 'image/jpeg', buffer: PHOTO,
  });
  await page.getByRole('button', { name: 'ENVOYER LA PHOTO' }).click();

  const apres = page.locator('section.carte', { hasText: libelle });
  await expect(apres).toContainText('Justificatif joint');
  await expect(apres.getByRole('button', { name: 'AJOUTER LA PHOTO' })).toHaveCount(0);
});

test('un fichier déguisé en photo est refusé et la dépense demeure', async ({ page }) => {
  await ouvrirLeDepart(page);
  const libelle = nature();
  const carte = await declarer(page, { nature: libelle, montant: '3200' });

  await carte.getByRole('button', { name: 'AJOUTER LA PHOTO' }).click();
  await page.getByLabel('Photo du ticket').setInputFiles({
    // Le nom et le type annoncés mentent ; le serveur lit les octets.
    name: 'ticket.jpg', mimeType: 'image/jpeg', buffer: FAUSSE_PHOTO,
  });
  await page.getByRole('button', { name: 'ENVOYER LA PHOTO' }).click();

  await expect(page.locator('p[role="alert"]')).toContainText('JPEG');
  await page.getByRole('button', { name: 'PLUS TARD' }).click();

  // La propriété centrale : l'argent sorti de la caisse est toujours là.
  const apres = page.locator('section.carte', { hasText: libelle });
  await expect(apres).toContainText('3 200');
  await expect(apres.getByRole('button', { name: 'AJOUTER LA PHOTO' })).toBeVisible();
});

test('la photo ne voyage jamais dans une adresse', async ({ page }) => {
  await ouvrirLeDepart(page);
  const libelle = nature();
  const carte = await declarer(page, { nature: libelle, montant: '1200' });

  const adresses: string[] = [];
  page.on('request', (requete) => adresses.push(requete.url()));

  await carte.getByRole('button', { name: 'AJOUTER LA PHOTO' }).click();
  await page.getByLabel('Photo du ticket').setInputFiles({
    name: 'ticket.jpg', mimeType: 'image/jpeg', buffer: PHOTO,
  });
  await page.getByRole('button', { name: 'ENVOYER LA PHOTO' }).click();
  await expect(page.locator('section.carte', { hasText: libelle }))
    .toContainText('Justificatif joint');

  for (const adresse of adresses) {
    expect(adresse).not.toContain('base64');
    expect(adresse).not.toContain('receipt=');
    expect(adresse).not.toContain('ticket.jpg');
  }
});

test('aucun identifiant Odoo ne descend dans la page', async ({ page }) => {
  await ouvrirLeDepart(page);
  await declarer(page, { nature: nature(), montant: '4400' });

  const html = (await page.content()).toLowerCase();
  for (const interdit of ['consolidation_id', 'company_id', 'currency_id',
                          'expense_id', 'attachment_id', 'external_expense_key',
                          'allocation_ids', 'ops:']) {
    expect(html).not.toContain(interdit.toLowerCase());
  }
});

test('un visiteur anonyme n’atteint aucune route de dépense', async ({ request }) => {
  expect((await request.get('/api/expense-consolidations')).status()).toBe(401);
  expect((await request.get(`/api/consolidations/${DEPART}/expenses`)).status()).toBe(401);

  const creation = await request.post('/api/expenses', {
    headers: { 'Content-Type': 'application/json' },
    data: { request_uuid: '11111111-2222-4333-8444-555555555555' },
  });
  expect(creation.status()).toBe(401);
});
