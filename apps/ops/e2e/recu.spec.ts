import { expect, request, test, type Page } from '@playwright/test';

/**
 * Le reçu remis au client, de bout en bout.
 *
 * Le parcours crée un vrai dossier Freight — donc un vrai `Axxx` attribué par
 * le serveur — puis ouvre son reçu. Ce que les assertions protègent : le
 * document ne se présente jamais comme une facture, il n'invente aucun solde
 * entre deux monnaies, il n'expose aucune adresse publique du PDF, et un
 * dossier resté dans la file hors connexion n'en a pas.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';

function referenceWave(): string {
  return `TWRC${Date.now().toString(36).toUpperCase()}`;
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

async function creerUnDossier(page: Page, designation: string): Promise<string> {
  await ouvrirLAccueil(page);
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();

  await page.getByLabel('Catégorie').fill('Alimentaire');
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

async function ouvrirLeRecu(page: Page, dossier: string) {
  await page.goto(`/reception/dossier/${encodeURIComponent(dossier)}`);
  await page.getByRole('link', { name: 'VOIR LE REÇU' }).click();
  await expect(page.getByText('REÇU DE PRISE EN CHARGE')).toBeVisible();
}

async function encaisser(page: Page, montant: string) {
  await page.getByRole('button', { name: 'PAIEMENT WAVE' }).click();
  await expect(page.getByTestId('formulaire-wave')).toBeVisible();
  await page.getByLabel('Montant').fill(montant);
  await page.getByLabel(/Référence Wave/).fill(referenceWave());
  const attendue = page.waitForResponse((reponse) =>
    reponse.url().includes('/payments') && reponse.request().method() === 'POST');
  await page.getByRole('button', { name: 'ENREGISTRER LE PAIEMENT WAVE' }).click();
  return attendue;
}

test('le reçu porte le dossier, le client et la marchandise', async ({ page }) => {
  const designation = `Épices céréales ${Date.now()}`;
  const dossier = await creerUnDossier(page, designation);
  await ouvrirLeRecu(page, dossier);

  await expect(page.getByText(dossier, { exact: false })).toBeVisible();
  await expect(page.getByText('Aissatou Kandji')).toBeVisible();
  await expect(page.getByText(designation)).toBeVisible();
  await expect(page.getByText('Aérien')).toBeVisible();
  // Un reçu, jamais une facture.
  await expect(page.getByText('Il ne constitue pas une facture')).toBeVisible();
});

test('sans paiement, le reçu le dit et n’affiche aucun montant reçu', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Sans paiement ${Date.now()}`);
  await ouvrirLeRecu(page, dossier);

  await expect(page.getByText('Aucun paiement reçu à ce jour')).toBeVisible();
  await expect(page.getByText('Montant reçu')).toHaveCount(0);
});

test('un encaissement Wave partiel apparaît sans solde inventé', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Wave partiel ${Date.now()}`);
  await page.goto(`/reception/dossier/${encodeURIComponent(dossier)}`);
  expect((await encaisser(page, '100000')).status()).toBe(200);

  await ouvrirLeRecu(page, dossier);
  await expect(page.getByText('100 000 FCFA').first()).toBeVisible();
  await expect(page.getByText('Wave').first()).toBeVisible();
  // Le tarif est en euros, l'encaissement en francs : aucun solde n'est arrêté.
  await expect(page.getByText('Voir le détail des paiements')).toBeVisible();
  await expect(page.getByText('ne sont pas dans la même monnaie')).toBeVisible();
});

test('deux paiements partiels restent deux mouvements sur le reçu', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Deux paiements ${Date.now()}`);
  await page.goto(`/reception/dossier/${encodeURIComponent(dossier)}`);
  expect((await encaisser(page, '100000')).status()).toBe(200);
  await page.goto(`/reception/dossier/${encodeURIComponent(dossier)}`);
  expect((await encaisser(page, '50000')).status()).toBe(200);

  await ouvrirLeRecu(page, dossier);
  await expect(page.getByText('100 000 FCFA').first()).toBeVisible();
  await expect(page.getByText('50 000 FCFA').first()).toBeVisible();
  // Le total ne remplace pas le détail.
  await expect(page.getByText('150 000 FCFA')).toBeVisible();
});

test('le reçu ne dépend d’aucun appel vers le classeur', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Sans Google ${Date.now()}`);

  const appels: string[] = [];
  page.on('request', (requete) => {
    const url = requete.url();
    if (url.includes('/api/')) appels.push(new URL(url).pathname);
  });
  await ouvrirLeRecu(page, dossier);

  // Aucun aller-retour vers Google, ni vers la file de projection : le reçu se
  // lit dans Odoo, et le classeur n'en est jamais une condition.
  for (const chemin of appels) {
    expect(chemin).not.toContain('sheet');
    expect(chemin).not.toContain('outbox');
    expect(chemin).not.toContain('google');
  }
  await expect(page.getByText('REÇU DE PRISE EN CHARGE')).toBeVisible();
});

test('aucune adresse publique ne mène au PDF', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Adresse PDF ${Date.now()}`);
  await ouvrirLeRecu(page, dossier);

  // La page n'offre aucun lien vers le document : les octets passent par une
  // requête portée par la session.
  await expect(page.locator('a[href*="receipt"]')).toHaveCount(0);

  // Et sans session, l'adresse du BFF ne rend rien : le reçu d'un client n'est
  // pas lisible par qui devine une référence de dossier.
  const base = new URL(page.url()).origin;
  const anonyme = await request.newContext({ baseURL: base });
  const refus = await anonyme.get(
    `/api/intakes/${encodeURIComponent(dossier)}/receipt/pdf`);
  expect(refus.status()).toBe(401);
  await anonyme.dispose();
});

test('le PDF se télécharge, et rien ne reste derrière', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Téléchargement ${Date.now()}`);
  await ouvrirLeRecu(page, dossier);

  const reponse = page.waitForResponse((r) => r.url().includes('/receipt/pdf'));
  const telechargement = page.waitForEvent('download');
  await page.getByRole('button', { name: 'TÉLÉCHARGER PDF' }).click();

  const recu = await reponse;
  expect(recu.status()).toBe(200);
  expect(recu.headers()['content-type']).toContain('application/pdf');
  // Rien ne doit rester dans un cache intermédiaire.
  expect(recu.headers()['cache-control']).toContain('no-store');

  const fichier = await telechargement;
  expect(fichier.suggestedFilename()).toBe(`Recu_DallyTrading_${dossier}.pdf`);
  // Le nom du client ne descend pas dans la liste des téléchargements.
  expect(fichier.suggestedFilename()).not.toContain('Aissatou');
});

test('le partage retombe sur le téléchargement quand il n’est pas possible', async ({ page }) => {
  await page.addInitScript(() => {
    // Un navigateur sans Web Share : le cas le plus courant sur un poste fixe.
    Object.defineProperty(navigator, 'share', { value: undefined, configurable: true });
  });
  const dossier = await creerUnDossier(page, `Partage absent ${Date.now()}`);
  await ouvrirLeRecu(page, dossier);

  const telechargement = page.waitForEvent('download');
  await page.getByRole('button', { name: 'PARTAGER' }).click();
  expect((await telechargement).suggestedFilename())
    .toBe(`Recu_DallyTrading_${dossier}.pdf`);
});

test('le partage utilise Web Share quand le système l’accepte', async ({ page }) => {
  await page.addInitScript(() => {
    const fenetre = window as unknown as { __partages: string[] };
    fenetre.__partages = [];
    Object.defineProperty(navigator, 'canShare', {
      value: () => true, configurable: true,
    });
    Object.defineProperty(navigator, 'share', {
      value: async (donnees: { files?: File[] }) => {
        fenetre.__partages.push(donnees.files?.[0]?.name ?? '');
      },
      configurable: true,
    });
  });
  const dossier = await creerUnDossier(page, `Partage présent ${Date.now()}`);
  await ouvrirLeRecu(page, dossier);
  await page.getByRole('button', { name: 'PARTAGER' }).click();

  await expect.poll(() => page.evaluate(
    () => (window as unknown as { __partages: string[] }).__partages,
  )).toEqual([`Recu_DallyTrading_${dossier}.pdf`]);
});

test('un dossier resté hors connexion n’a pas de reçu', async ({ page }) => {
  await ouvrirLAccueil(page);
  // Une référence locale n'est pas un dossier : elle ne désigne rien côté
  // serveur, et un reçu portant un numéro né dans le téléphone ne renverrait
  // à rien.
  await page.goto('/reception/dossier/LOCAL-abcdef1234/recu');
  // Le reçu renvoie au dossier, qui renvoie lui-même à la liste : une
  // référence locale ne désigne rien, à aucun des deux étages.
  await expect(page).toHaveURL(/\/reception$/);
  await expect(page.getByText('REÇU DE PRISE EN CHARGE')).toHaveCount(0);
});

test('le reçu n’est jamais conservé par le Service Worker', async ({ page }) => {
  const dossier = await creerUnDossier(page, `Cache ${Date.now()}`);
  await ouvrirLeRecu(page, dossier);
  await page.getByRole('button', { name: 'TÉLÉCHARGER PDF' }).click();
  await page.waitForResponse((r) => r.url().includes('/receipt/pdf'));

  const gardees = await page.evaluate(async () => {
    if (!('caches' in window)) return [];
    const noms = await caches.keys();
    const urls: string[] = [];
    for (const nom of noms) {
      const cache = await caches.open(nom);
      for (const requete of await cache.keys()) urls.push(requete.url);
    }
    return urls;
  });
  for (const url of gardees) {
    expect(url).not.toContain('/api/');
    expect(url).not.toContain('receipt');
  }
});
