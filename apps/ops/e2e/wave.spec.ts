import { expect, test, type Page } from '@playwright/test';

/**
 * Encaisser par Wave, jusque dans le CRM.
 *
 * Le parcours crée un vrai dossier Freight — donc un vrai `Axxx` attribué par
 * le serveur — puis enregistre un encaissement Wave dessus. Ce que les
 * assertions protègent : l'écran n'invente ni le bénéficiaire ni le moyen, un
 * rejeu ne double pas la ligne, et un second encaissement partiel s'ajoute
 * sans écraser le premier.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';

/** Un numéro neuf par exécution : la base du banc n'est pas remise à zéro. */
function referenceWave(): string {
  return `TWE2E${Date.now().toString(36).toUpperCase()}`;
}

async function ouvrirLAccueil(page: Page) {
  await page.goto('/');
  if (/\/connexion$/.test(page.url())) {
    await page.getByLabel('Identifiant').fill(OPERATEUR.login);
    await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
    await page.getByRole('button', { name: 'Se connecter' }).click();
  }
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();
}

/** Une vraie réception, et le `Axxx` que le serveur lui a donné. */
async function creerUnDossier(page: Page, designation: string): Promise<string> {
  await ouvrirLAccueil(page);
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

async function ouvrirLeDossier(page: Page, reference: string) {
  await page.goto(`/reception/dossier/${encodeURIComponent(reference)}`);
  await expect(page.getByRole('heading', { name: /^DOSSIER A\d{3}$/ })).toBeVisible();
}

async function encaisser(
  page: Page,
  { montant, reference }: { montant: string; reference: string },
) {
  await page.getByRole('button', { name: 'PAIEMENT WAVE' }).click();
  await expect(page.getByTestId('formulaire-wave')).toBeVisible();
  await page.getByLabel('Montant').fill(montant);
  await page.getByLabel(/Référence Wave/).fill(reference);
  const attendue = page.waitForResponse((reponse) =>
    reponse.url().includes('/payments') && reponse.request().method() === 'POST');
  await page.getByRole('button', { name: 'ENREGISTRER LE PAIEMENT WAVE' }).click();
  return attendue;
}

test('le bénéficiaire et le moyen viennent du serveur, non de l’écran', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave E2E ${Date.now()}`);
  await ouvrirLeDossier(page, dossier);
  await page.getByRole('button', { name: 'PAIEMENT WAVE' }).click();

  await expect(page.getByTestId('beneficiaire-wave')).toHaveText('GILLES');
  await expect(page.getByTestId('client-wave')).toHaveText('Aissatou Kandji');
  // Ni l'un ni l'autre ne se saisit : aucun champ ne les porte.
  await expect(page.locator('input[name="beneficiary"]')).toHaveCount(0);
  await expect(page.locator('input[name="payment_method"]')).toHaveCount(0);
  await expect(page.locator('select#mode-paiement')).toHaveCount(0);
});

test('un encaissement Wave est enregistré sur le vrai dossier', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave E2E ${Date.now()}`);
  await ouvrirLeDossier(page, dossier);

  const reponse = await encaisser(page, { montant: '100000', reference: referenceWave() });
  expect(reponse.status()).toBe(200);
  const charge = await reponse.json() as {
    data: { status: string; payment: { beneficiary: string; payment_method: string } };
  };
  expect(charge.data.status).toBe('created');
  expect(charge.data.payment.beneficiary).toBe('Gilles');
  expect(charge.data.payment.payment_method).toBe('wave');

  await expect(page.getByTestId('paiement').first()).toContainText('100 000');
  await expect(page.getByTestId('paiement').first()).toContainText('Gilles');
  await expect(page.getByTestId('paiement').first()).toContainText('Wave');
});

test('un rejeu du même envoi ne crée pas un second encaissement', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave E2E ${Date.now()}`);
  await ouvrirLeDossier(page, dossier);
  const wave = referenceWave();
  const premier = await encaisser(page, { montant: '100000', reference: wave });
  const referencePublique =
    (await premier.json() as { data: { payment: { reference: string } } })
      .data.payment.reference;

  // Le même identifiant de demande, tel que le renverrait une reprise réseau.
  const rejeu = await page.request.post(
    `/api/shipments/${encodeURIComponent(dossier)}/payments`,
    {
      headers: { 'Content-Type': 'application/json' },
      data: {
        request_uuid: referencePublique,
        amount: 100000,
        currency: 'XOF',
        wave_reference: wave,
        paid_at: new Date().toISOString().slice(0, 10),
        note: '',
      },
    });
  expect(rejeu.status()).toBe(200);
  const charge = await rejeu.json() as {
    data: { status: string; payment: { reference: string } };
  };
  expect(charge.data.status).toBe('replayed');
  expect(charge.data.payment.reference).toBe(referencePublique);

  await page.reload();
  await expect(page.getByTestId('paiement')).toHaveCount(1);
});

test('un second encaissement partiel s’ajoute sans écraser le premier', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave E2E ${Date.now()}`);
  await ouvrirLeDossier(page, dossier);

  await encaisser(page, { montant: '100000', reference: referenceWave() });
  await expect(page.getByTestId('formulaire-wave')).toHaveCount(0);
  await encaisser(page, { montant: '50000', reference: referenceWave() });
  await expect(page.getByTestId('formulaire-wave')).toHaveCount(0);

  // Deux lignes distinctes, et aucune n'a écrasé l'autre. Le bloc de résumé
  // n'apparaît qu'à partir de deux devises — ici tout est en francs, et il
  // n'aurait rien à dire de plus que les lignes elles-mêmes.
  await expect(page.getByTestId('paiement')).toHaveCount(2);
  const lignes = page.getByTestId('paiement');
  await expect(lignes.filter({ hasText: '100 000' })).toHaveCount(1);
  await expect(lignes.filter({ hasText: '50 000' })).toHaveCount(1);

  // Et le serveur les rend bien tous deux sur le même dossier.
  const liste = await page.request.get(
    `/api/shipments/${encodeURIComponent(dossier)}/payments`);
  expect(liste.status()).toBe(200);
  const charge = await liste.json() as {
    data: { intake_reference: string;
            items: { amount: number; beneficiary: string }[];
            summary: { currency_code: string; amount: number }[] };
  };
  expect(charge.data.intake_reference).toBe(dossier);
  expect(charge.data.items).toHaveLength(2);
  expect(charge.data.items.every((item) => item.beneficiary === 'Gilles')).toBe(true);
  expect(charge.data.summary).toEqual([{ currency_code: 'XOF', amount: 150000 }]);
});

test('un montant nul est refusé sans atteindre le serveur', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave E2E ${Date.now()}`);
  await ouvrirLeDossier(page, dossier);

  const envois: string[] = [];
  page.on('request', (requete) => {
    if (requete.url().includes('/payments') && requete.method() === 'POST') {
      envois.push(requete.url());
    }
  });

  await page.getByRole('button', { name: 'PAIEMENT WAVE' }).click();
  await page.getByLabel('Montant').fill('0');
  await page.getByRole('button', { name: 'ENREGISTRER LE PAIEMENT WAVE' }).click();
  await expect(page.locator('p[role="alert"]')).toBeVisible();
  expect(envois).toHaveLength(0);
});

test('aucun identifiant Odoo ne descend dans la page', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave E2E ${Date.now()}`);
  await ouvrirLeDossier(page, dossier);
  await encaisser(page, { montant: '75000', reference: referenceWave() });
  await expect(page.getByTestId('paiement').first()).toBeVisible();

  const html = (await page.content()).toLowerCase();
  for (const interdit of ['partner_id', 'shipment_id', 'invoice_id', 'company_id',
                          'collection_id', 'account_payment', 'journal_id',
                          'external_payment_key', 'error_message']) {
    expect(html).not.toContain(interdit.toLowerCase());
  }
  // Voir `paiements.spec.ts` : « ops: » nu entre en collision avec « props: »
  // des références React Flight. La clé de source a une forme, on la cherche.
  expect(html).not.toMatch(/ops:[0-9a-f]{8}/);
});

test('un visiteur anonyme n’atteint aucune route d’encaissement', async ({ request }) => {
  const contexte = await request.get(
    `/api/shipments/${DEPART}-A001/wave-context`);
  expect(contexte.status()).toBe(401);

  const paiement = await request.post(
    `/api/shipments/${DEPART}-A001/payments`,
    {
      headers: { 'Content-Type': 'application/json' },
      data: { request_uuid: '11111111-2222-4333-8444-555555555555' },
    });
  expect(paiement.status()).toBe(401);
});
