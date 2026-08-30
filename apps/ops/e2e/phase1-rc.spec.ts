import { expect, test, type Page } from '@playwright/test';

/**
 * Les deux parcours de synthèse de la Phase 1.
 *
 * Les autres suites éprouvent chacune une fonctionnalité. Celles-ci traversent
 * le produit entier — agenda, réception, tarification, numérotation serveur,
 * encaissement, reçu, journal — parce qu'un défaut d'intégration se cache
 * précisément entre deux étapes vertes.
 */

const GILLES = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';
const CLIENT_NOM = 'Aissatou Kandji';

async function seConnecter(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(GILLES.login);
  await page.getByLabel('Mot de passe').fill(GILLES.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: /^Bonjour / })).toBeVisible();
}

async function choisirLeClient(page: Page) {
  await page.getByLabel('Numéro de téléphone').fill(CLIENT);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toContainText(CLIENT_NOM);
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();
}

async function remplirArticle(
  page: Page,
  { designation, poids, famille, categorie }:
  { designation: string; poids: string; famille: string; categorie: string },
) {
  await page.getByLabel('Catégorie').fill(categorie);
  await page.getByLabel('Désignation').fill(designation);
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill(poids);
  await page.getByLabel('Famille tarifaire').selectOption(famille);
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
}

test('de l’agenda au journal : un dossier traverse toute la Phase 1', async ({ page }) => {
  const marqueur = `RC ${Date.now()}`;
  await seConnecter(page);

  // ── Agenda : le rendez-vous, puis l'arrivée du client ────────────
  await page.getByRole('link', { name: /Agenda/ }).click();
  await page.getByRole('button', { name: '+ NOUVEAU RENDEZ-VOUS' }).click();
  await choisirLeClient(page);
  await page.getByLabel('Type de rendez-vous').selectOption('dropoff');
  await page.getByLabel('Date et heure').fill('2026-08-31T10:00');
  await page.getByLabel('Durée').selectOption('30');
  await page.getByLabel('Départ').selectOption(DEPART);
  await page.getByLabel('Lieu').fill('Dépôt Dakar');
  await page.getByLabel('Note').fill(marqueur);
  await page.getByRole('button', { name: 'ENREGISTRER LE RENDEZ-VOUS' }).click();
  await expect(page.getByRole('heading', { name: CLIENT_NOM.toUpperCase() })).toBeVisible();

  await page.getByRole('button', { name: 'CLIENT PRÉSENT' }).click();
  await expect(page.getByText('✓ CLIENT PRÉSENT')).toBeVisible();

  // ── Préparer la réception : aucun numéro n'est consommé ici ──────
  const appelsIntake: string[] = [];
  page.on('request', (requete) => {
    if (requete.url().endsWith('/api/intakes')) appelsIntake.push(requete.method());
  });
  await page.getByRole('button', { name: 'RÉCEPTIONNER LE COLIS' }).click();
  await expect(page).toHaveURL(/\/reception\/colis\/preparee$/);
  await expect(page.getByTestId('client-selectionne')).toHaveText(CLIENT_NOM);
  await expect(page.getByTestId('consolidation-selectionnee')).toHaveText(DEPART);
  expect(appelsIntake.filter((m) => m === 'POST')).toHaveLength(0);

  // ── Réception : trois familles tarifaires différentes ────────────
  await remplirArticle(page, {
    designation: `${marqueur} riz`, poids: '13.5',
    famille: 'food', categorie: 'Alimentaire',
  });
  const creation = page.waitForResponse((r) =>
    r.url().endsWith('/api/intakes') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
  const reference = (await (await creation).json() as {
    data: { intake: { reference: string; local_reference: string } };
  }).data.intake;

  // Le numéro vient du serveur et porte la consolidation.
  expect(reference.reference).toMatch(new RegExp(`^${DEPART}-A\\d{3}$`));
  expect(reference.local_reference).toMatch(/^A\d{3}$/);

  await page.goto(`/reception/dossier/${encodeURIComponent(reference.reference)}`);
  for (const article of [
    { designation: `${marqueur} savon`, poids: '4.5',
      famille: 'non_food', categorie: 'Non alimentaire' },
    { designation: `${marqueur} boubou`, poids: '2.0',
      famille: 'clothing', categorie: 'Vêtements' },
  ]) {
    await page.getByRole('button', { name: '+ AJOUTER UN ARTICLE' }).click();
    await remplirArticle(page, article);
    await page.getByRole('button', { name: 'ENREGISTRER L’ARTICLE' }).click();
    await expect(page.getByTestId('totaux')).toBeVisible();
  }
  await expect(page.getByTestId('article')).toHaveCount(3);
  await expect(page.getByTestId('totaux')).toContainText('3 article(s)');
  await expect(page.getByTestId('totaux')).toContainText('20,00 kg');

  // ── Encaissement Wave : le serveur décide du moyen et du bénéficiaire ──
  await page.getByRole('button', { name: 'PAIEMENT WAVE' }).click();
  await expect(page.getByTestId('beneficiaire-wave')).toHaveText('GILLES');
  await page.getByLabel('Montant').fill('100000');
  await page.getByLabel(/Référence Wave/).fill(`TWRC${Date.now().toString(36).toUpperCase()}`);
  const paiement = page.waitForResponse((r) =>
    r.url().includes('/payments') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'ENREGISTRER LE PAIEMENT WAVE' }).click();
  const charge = await (await paiement).json() as {
    data: { payment: { beneficiary: string; payment_method: string } };
  };
  expect(charge.data.payment.beneficiary).toBe('Gilles');
  expect(charge.data.payment.payment_method).toBe('wave');

  // ── Reçu : le contrat, puis les octets du PDF ────────────────────
  const contrat = await page.request.get(
    `/api/intakes/${encodeURIComponent(reference.reference)}/receipt`);
  expect(contrat.status()).toBe(200);
  const recu = (await contrat.json() as {
    data: { receipt: {
      reference: string; customer: { name: string };
      articles: unknown[]; payments: { amount_display: string }[];
      totals: { articles_count: number; weight_display: string };
    } };
  }).data.receipt;
  expect(recu.reference).toBe(reference.reference);
  expect(recu.customer.name).toBe(CLIENT_NOM);
  expect(recu.articles).toHaveLength(3);
  expect(recu.totals.articles_count).toBe(3);
  expect(recu.totals.weight_display).toBe('20 kg');
  expect(recu.payments[0]?.amount_display).toBe('100 000 FCFA');
  // Aucun identifiant interne dans le document remis au client.
  const rendu = JSON.stringify(recu);
  for (const interne of ['shipment_id', 'partner_id', 'request_uuid', 'invoice_id']) {
    expect(rendu).not.toContain(interne);
  }

  const pdf = await page.request.get(
    `/api/intakes/${encodeURIComponent(reference.reference)}/receipt/pdf`);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()['content-type']).toContain('application/pdf');
  expect(pdf.headers()['cache-control']).toContain('no-store');
  const octets = await pdf.body();
  expect(octets.subarray(0, 4).toString()).toBe('%PDF');
  expect(octets.byteLength).toBeGreaterThan(1000);

  // ── Journal : le dossier raconte ce qui vient de se passer ───────
  await page.goto(`/reception/dossier/${encodeURIComponent(reference.reference)}`);
  const timeline = page.locator('.timeline-activite');
  await expect(timeline.locator('li').filter({ hasText: 'Réception enregistrée' }))
    .toHaveCount(1);
  await expect(timeline.locator('li').filter({ hasText: 'Article ajouté' }))
    .toHaveCount(2);
  const wave = timeline.locator('li').filter({ hasText: 'Paiement Wave' });
  await expect(wave).toHaveCount(1);
  await expect(wave).toContainText('100 000 FCFA');
  await expect(wave).toContainText('Gilles');
});

test('hors connexion puis reconnexion : un dossier, un numéro, un journal',
  async ({ page, context }) => {
    const marqueur = `RC offline ${Date.now()}`;
    await seConnecter(page);

    await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
    await page.locator('section.carte', { hasText: DEPART })
      .getByRole('link', { name: 'Sélectionner' }).click();
    await choisirLeClient(page);
    await remplirArticle(page, {
      designation: marqueur, poids: '13.5',
      famille: 'non_food', categorie: 'Non alimentaire',
    });

    await context.setOffline(true);
    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
    await expect(page.getByTestId('reception-en-file')).toBeVisible();
    // Aucun numéro inventé, aucun reçu, aucun événement serveur.
    await expect(page.getByTestId('reception-en-file')).not.toContainText(/A\d{3}/);

    await context.setOffline(false);
    const avant = await page.request.get('/api/activity?limit=100');
    expect(JSON.stringify(await avant.json())).not.toContain(marqueur);

    await page.getByRole('button', { name: 'VOIR LES OPÉRATIONS EN ATTENTE' }).click();
    await page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' }).click();
    const synchronisee = page.getByTestId('operation-synchronisee');
    await expect(synchronisee).toHaveCount(1, { timeout: 15_000 });
    const reference = ((await synchronisee.textContent()) ?? '')
      .match(new RegExp(`${DEPART}-A\\d{3}`))?.[0] ?? '';
    expect(reference).not.toBe('');

    // Le reçu existe désormais, et le journal porte une seule réception.
    const recu = await page.request.get(
      `/api/intakes/${encodeURIComponent(reference)}/receipt`);
    expect(recu.status()).toBe(200);

    await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
    await expect(page.locator('.timeline-activite').locator('li')
      .filter({ hasText: 'Réception enregistrée' })).toHaveCount(1);

    // Une seconde synchronisation ne recrée rien.
    await page.goto('/synchronisation');
    const bouton = page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' });
    if (await bouton.count()) await bouton.click();
    await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
    await expect(page.locator('.timeline-activite').locator('li')
      .filter({ hasText: 'Réception enregistrée' })).toHaveCount(1);
  });
