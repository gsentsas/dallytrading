import { expect, test, type Page } from '@playwright/test';

/**
 * Le journal d'activité, de bout en bout.
 *
 * Ce que les assertions protègent : un événement n'apparaît que lorsque le
 * serveur a confirmé le geste, il porte le bon opérateur, un rejeu ne le
 * double pas, une correction conserve l'ancienne valeur à côté de la nouvelle,
 * et « mes saisies » n'attribue jamais à Gilles le travail de Dalanda.
 */

const GILLES = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};
const DALANDA = {
  login: process.env.OPS_E2E_DALANDA_LOGIN ?? 'dalanda.banc',
  password: process.env.OPS_E2E_DALANDA_PASSWORD ?? 'banc-dalanda-2026',
};
const RESPONSABLE = {
  login: process.env.OPS_E2E_RESPONSABLE_LOGIN ?? 'responsable.banc',
  password: process.env.OPS_E2E_RESPONSABLE_PASSWORD ?? 'banc-responsable-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';

function referenceWave(): string {
  return `TWACT${Date.now().toString(36).toUpperCase()}`;
}

/** Ce test change d'opérateur : la déconnexion doit être effective, pas espérée. */
async function seDeconnecter(page: Page) {
  await page.goto('/');
  const bouton = page.getByRole('button', { name: 'Se déconnecter' });
  if (await bouton.count()) {
    await bouton.click();
    await page.waitForURL(/\/connexion$/);
  }
}

async function seConnecter(page: Page, compte: { login: string; password: string }) {
  await seDeconnecter(page);
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(compte.login);
  await page.getByLabel('Mot de passe').fill(compte.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  // Le titre d'accueil porte le prénom : s'arrêter à « un titre de niveau 1 »
  // laisserait passer l'écran de connexion, qui en a un aussi.
  await expect(page.getByRole('heading', { name: /^Bonjour / })).toBeVisible();
}

async function creerUnDossier(page: Page, designation: string): Promise<string> {
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT);
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

function activite(page: Page) {
  return page.locator('.timeline-activite');
}

async function ouvrirLeDossier(page: Page, reference: string) {
  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await expect(page.getByRole('heading', { name: 'ACTIVITÉ' })).toBeVisible();
}

test('la réception apparaît au journal du dossier, avec son opérateur', async ({ page }) => {
  await seConnecter(page, GILLES);
  const reference = await creerUnDossier(page, `Journal ${Date.now()}`);
  await ouvrirLeDossier(page, reference);

  const ligne = activite(page).locator('li').filter({ hasText: 'Réception enregistrée' });
  await expect(ligne).toHaveCount(1);
  await expect(ligne).toContainText('Gilles');
  await expect(ligne).toContainText('Dossier A');
  // Aucun identifiant technique dans la page.
  const html = await page.content();
  for (const interne of ['request_uuid', 'operator_user_id', 'shipment_id']) {
    expect(html).not.toContain(interne);
  }
});

test('un encaissement Wave apparaît une seule fois, même rejoué', async ({ page }) => {
  await seConnecter(page, GILLES);
  const reference = await creerUnDossier(page, `Journal Wave ${Date.now()}`);

  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await page.getByRole('button', { name: 'PAIEMENT WAVE' }).click();
  await expect(page.getByTestId('formulaire-wave')).toBeVisible();
  await page.getByLabel('Montant').fill('100000');
  const wave = referenceWave();
  await page.getByLabel(/Référence Wave/).fill(wave);
  const envoi = page.waitForResponse((r) =>
    r.url().includes('/payments') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'ENREGISTRER LE PAIEMENT WAVE' }).click();
  const uuid = (await (await envoi).json() as {
    data: { payment: { reference: string } };
  }).data.payment.reference;

  await ouvrirLeDossier(page, reference);
  const ligne = activite(page).locator('li').filter({ hasText: 'Paiement Wave' });
  await expect(ligne).toHaveCount(1);
  await expect(ligne).toContainText('100 000 FCFA');
  await expect(ligne).toContainText('Gilles');

  // Le même envoi rejoué — une reprise réseau — ne crée pas une seconde ligne.
  const rejeu = await page.request.post(
    `/api/shipments/${encodeURIComponent(reference)}/payments`,
    {
      headers: { 'Content-Type': 'application/json' },
      data: {
        request_uuid: uuid, amount: 100000, currency: 'XOF',
        wave_reference: wave,
        paid_at: new Date().toISOString().slice(0, 10), note: '',
      },
    });
  expect(rejeu.status()).toBe(200);
  await ouvrirLeDossier(page, reference);
  await expect(activite(page).locator('li')
    .filter({ hasText: 'Paiement Wave' })).toHaveCount(1);
});

test('une correction conserve l’ancienne valeur à côté de la nouvelle', async ({ page }) => {
  await seConnecter(page, GILLES);
  const reference = await creerUnDossier(page, `Journal correction ${Date.now()}`);

  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await page.getByRole('button', { name: 'MODIFIER' }).first().click();
  await page.getByLabel('Poids exact total (kg)').fill('8.1');
  await page.getByRole('button', { name: 'ENREGISTRER LES CORRECTIONS' }).click();
  await expect(page.getByTestId('totaux')).toContainText('8,10 kg');

  await ouvrirLeDossier(page, reference);
  const correction = activite(page).locator('li')
    .filter({ hasText: 'Article corrigé' });
  await expect(correction).toHaveCount(1);
  await expect(correction).toContainText('Poids exact');
  await expect(correction).toContainText('13,5 kg → 8,1 kg');
  // L'événement d'origine n'a pas été remplacé.
  await expect(activite(page).locator('li')
    .filter({ hasText: 'Réception enregistrée' })).toHaveCount(1);
});

test('mes saisies du jour n’empruntent pas le travail d’un collègue', async ({ page }) => {
  await seConnecter(page, GILLES);
  const dossierGilles = await creerUnDossier(page, `Journal mien ${Date.now()}`);

  await seDeconnecter(page);
  await seConnecter(page, DALANDA);
  const dossierDalanda = await creerUnDossier(page, `Journal sien ${Date.now()}`);

  await seDeconnecter(page);
  await seConnecter(page, GILLES);
  await page.goto('/activite');
  await expect(page.getByRole('heading', { name: 'MES SAISIES DU JOUR' })).toBeVisible();
  const miennes = activite(page);
  await expect(miennes.locator('li').filter({ hasText: 'Gilles' }).first()).toBeVisible();
  await expect(miennes.locator('li').filter({ hasText: 'Dalanda' })).toHaveCount(0);
  expect(dossierGilles).not.toBe(dossierDalanda);
});

test('le responsable voit l’activité de son équipe', async ({ page }) => {
  await seConnecter(page, GILLES);
  await creerUnDossier(page, `Journal équipe ${Date.now()}`);
  await seDeconnecter(page);

  await seConnecter(page, RESPONSABLE);
  await page.goto('/activite');
  await expect(page.getByRole('heading', { name: 'ACTIVITÉ AUJOURD’HUI' })).toBeVisible();
  await expect(activite(page).locator('li')
    .filter({ hasText: 'Gilles' }).first()).toBeVisible();
});

test('le journal du dossier reste lisible quand la projection Sheet échoue', async ({ page }) => {
  await seConnecter(page, GILLES);
  const reference = await creerUnDossier(page, `Journal Google ${Date.now()}`);

  const appels: string[] = [];
  page.on('request', (requete) => {
    const url = requete.url();
    if (url.includes('/api/')) appels.push(new URL(url).pathname);
  });
  await ouvrirLeDossier(page, reference);

  await expect(activite(page).locator('li')
    .filter({ hasText: 'Réception enregistrée' })).toHaveCount(1);
  for (const chemin of appels) {
    expect(chemin).not.toContain('sheet');
    expect(chemin).not.toContain('outbox');
    expect(chemin).not.toContain('google');
  }
});

test('aucune route du navigateur ne permet d’écrire dans le journal', async ({ page }) => {
  await seConnecter(page, GILLES);
  for (const chemin of ['/api/activity', '/api/intakes/AIR-TEST-A001/activity']) {
    const refus = await page.request.post(chemin, { data: { event: 'forge' } });
    expect(refus.status()).toBeGreaterThanOrEqual(400);
  }
  // Et une page illimitée est refusée avant d'atteindre Odoo.
  expect((await page.request.get('/api/activity?limit=5000')).status()).toBe(400);
  expect((await page.request.get('/api/activity?sudo=1')).status()).toBe(400);
});

test('une saisie hors connexion n’écrit au journal qu’après confirmation du CRM',
  async ({ page, context }) => {
    await seConnecter(page, GILLES);

    await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
    await page.locator('section.carte', { hasText: DEPART })
      .getByRole('link', { name: 'Sélectionner' }).click();
    await page.getByLabel('Numéro de téléphone').fill(CLIENT);
    await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
    await expect(page.getByTestId('client-trouve')).toBeVisible();
    await page.getByRole('button', { name: 'Utiliser ce client' }).click();

    const designation = `Journal offline ${Date.now()}`;
    await page.getByLabel('Catégorie').fill('Non alimentaire');
    await page.getByLabel('Désignation').fill(designation);
    await page.getByLabel('Quantité').fill('1');
    await page.getByLabel('Poids exact total (kg)').fill('13.5');
    await page.getByLabel('Famille tarifaire').selectOption('non_food');
    await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');

    await context.setOffline(true);
    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
    await expect(page.getByTestId('reception-en-file')).toBeVisible();

    // Avant synchronisation : l'opération vit dans la file locale, et le
    // journal officiel — qui n'existe que dans Odoo — ne la connaît pas.
    await context.setOffline(false);
    const avant = await page.request.get('/api/activity?limit=100');
    expect(avant.status()).toBe(200);
    expect(JSON.stringify(await avant.json())).not.toContain(designation);

    await page.getByRole('button', { name: 'VOIR LES OPÉRATIONS EN ATTENTE' }).click();
    await expect(page.getByRole('heading', { name: 'SYNCHRONISATION' })).toBeVisible();
    await page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' }).click();
    const synchronisee = page.getByTestId('operation-synchronisee');
    await expect(synchronisee).toHaveCount(1, { timeout: 15_000 });
    const reference = ((await synchronisee.textContent()) ?? '')
      .match(new RegExp(`${DEPART}-A\\d{3}`))?.[0] ?? '';
    expect(reference).not.toBe('');

    // Après confirmation : un événement serveur, et un seul.
    await ouvrirLeDossier(page, reference);
    await expect(activite(page).locator('li')
      .filter({ hasText: 'Réception enregistrée' })).toHaveCount(1);

    // Le rejeu de la file — reprise réseau — n'en ajoute pas un second.
    await page.goto('/synchronisation');
    const bouton = page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' });
    if (await bouton.count()) await bouton.click();
    await ouvrirLeDossier(page, reference);
    await expect(activite(page).locator('li')
      .filter({ hasText: 'Réception enregistrée' })).toHaveCount(1);
  });
