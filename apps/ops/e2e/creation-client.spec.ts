import { expect, test, type Page } from '@playwright/test';

/**
 * Créer un client au comptoir, de bout en bout.
 *
 * Deux parcours comptent ici. Le premier est le cas nominal. Le second est
 * celui qui justifie tout le mécanisme : le serveur refait la recherche au
 * moment d'écrire, et retrouve une fiche que l'écran précédent ne connaissait
 * pas.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const INCONNU = '+221 77 999 88 77';
/** Fiche présente en base, que la recherche précédente n'a pas vue. */
const DEJA_EN_BASE = '+221 76 555 44 33';

/** Un numéro neuf à chaque exécution : le banc garde ce qu'on y crée. */
function numeroNeuf(): string {
  const suffixe = String(Math.floor(Math.random() * 1_000_000)).padStart(6, '0');
  return `+221 78 ${suffixe.slice(0, 3)} ${suffixe.slice(3)} 21`;
}

async function ouvrirLeFormulaire(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(OPERATEUR.login);
  await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();

  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();

  await page.getByLabel('Numéro de téléphone').fill(INCONNU);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('introuvable')).toBeVisible();
  await page.getByRole('button', { name: 'Créer un nouveau client' }).click();
  await expect(page.getByRole('heading', { name: 'Nouveau client' })).toBeVisible();
}

async function remplir(page: Page, valeurs: { nom: string; tel: string; adresse: string }) {
  await page.getByLabel('Nom et prénom').fill(valeurs.nom);
  await page.getByLabel('Téléphone').fill(valeurs.tel);
  await page.getByLabel('Adresse').fill(valeurs.adresse);
}

test('le formulaire s’adapte au type de client', async ({ page }) => {
  await ouvrirLeFormulaire(page);
  await expect(page.getByLabel('Nom et prénom')).toBeVisible();

  await page.getByRole('button', { name: 'Professionnel' }).click();
  await expect(page.getByLabel('Raison sociale')).toBeVisible();
  await expect(page.getByLabel('Nom et prénom')).toHaveCount(0);
});

test('aucun champ ERP n’est proposé', async ({ page }) => {
  await ouvrirLeFormulaire(page);
  for (const interdit of ['is_company', 'company_id', 'partner_id',
                          'credit_limit', 'user_id']) {
    await expect(page.locator(`[name="${interdit}"]`)).toHaveCount(0);
  }
});

test('la validation locale retient une saisie incomplète', async ({ page }) => {
  await ouvrirLeFormulaire(page);

  const envois: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/customers') && r.method() === 'POST') envois.push(r.url());
  });

  await remplir(page, { nom: 'Test Incomplet', tel: '77', adresse: 'Quelque part' });
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();
  await expect(page.locator('p[role="alert"]')).toContainText('9 chiffres au minimum');
  expect(envois).toHaveLength(0);

  await page.getByLabel('Téléphone').fill(numeroNeuf());
  await page.getByLabel('Adresse').fill('');
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();
  await expect(page.locator('p[role="alert"]')).toContainText('adresse est obligatoire');
  expect(envois).toHaveLength(0);
});

test('un client neuf est créé et mène aux colis', async ({ page }) => {
  await ouvrirLeFormulaire(page);
  await remplir(page, {
    nom: 'Nouvelle Cliente E2E',
    tel: numeroNeuf(),
    adresse: '5 rue de la Réception, Dakar',
  });
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();

  await expect(page.getByTestId('client-cree')).toBeVisible();
  await expect(page.getByText('Nouvelle Cliente E2E')).toBeVisible();

  await page.getByRole('button', { name: 'Continuer vers les colis' }).click();
  await expect(page.getByRole('heading', { name: 'DOSSIER EN COURS' })).toBeVisible();
  await expect(page.getByTestId('consolidation-selectionnee')).toHaveText(DEPART);
  expect(page.url()).toMatch(
    /customer=[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/);
});

test('une fiche apparue depuis la recherche est retrouvée, pas dupliquée', async ({ page }) => {
  // Le scénario qui justifie la recherche refaite sous verrou : l'écran a dit
  // « aucun client trouvé » pour un autre numéro, mais celui-ci existe déjà.
  await ouvrirLeFormulaire(page);
  await remplir(page, {
    nom: 'Ousmane B.',
    tel: DEJA_EN_BASE,
    adresse: 'Une adresse saisie au comptoir',
  });
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();

  await expect(page.getByTestId('client-existant')).toBeVisible();
  await expect(page.getByText('Ousmane Ba')).toBeVisible();
  await expect(page.getByText('La fiche existante a été retrouvée.')).toBeVisible();

  await page.getByRole('button', { name: 'Utiliser ce client' }).click();
  await expect(page.getByRole('heading', { name: 'DOSSIER EN COURS' })).toBeVisible();
});

test('une tentative rejouée porte le même identifiant de demande', async ({ page }) => {
  await ouvrirLeFormulaire(page);

  const identifiants: string[] = [];
  let premiereTentative = true;
  await page.route('**/api/customers', async (route) => {
    const corps = route.request().postDataJSON() as { request_uuid: string };
    identifiants.push(corps.request_uuid);
    if (premiereTentative) {
      // La réponse se perd, comme sur une 4G d'entrepôt.
      premiereTentative = false;
      await route.abort('failed');
      return;
    }
    await route.continue();
  });

  await remplir(page, {
    nom: 'Client Rejoué E2E',
    tel: numeroNeuf(),
    adresse: 'Zone industrielle, Dakar',
  });
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();
  await expect(page.locator('p[role="alert"]')).toBeVisible();

  await page.getByRole('button', { name: 'Enregistrer le client' }).click();
  await expect(page.getByTestId('client-cree')).toBeVisible();

  expect(identifiants).toHaveLength(2);
  // Régénérer l'identifiant à chaque tentative créerait un doublon dès que le
  // réseau hésite.
  expect(identifiants[0]).toBe(identifiants[1]);
});

test('aucune donnée personnelle ne voyage dans une URL', async ({ page }) => {
  const urls: string[] = [];
  page.on('request', (requete) => urls.push(requete.url()));

  await ouvrirLeFormulaire(page);
  const numero = numeroNeuf();
  await remplir(page, {
    nom: 'Sans Fuite E2E', tel: numero, adresse: '1 rue Discrète, Dakar',
  });
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();
  await expect(page.getByTestId('client-cree')).toBeVisible();
  await page.getByRole('button', { name: 'Continuer vers les colis' }).click();
  await expect(page.getByRole('heading', { name: 'DOSSIER EN COURS' })).toBeVisible();

  const chiffres = numero.replace(/\D/g, '');
  for (const url of [...urls, page.url()]) {
    expect(url).not.toContain('Sans Fuite');
    expect(url).not.toContain(chiffres);
    expect(url).not.toContain('partner_id');
  }
});

test('aucun identifiant Odoo ni secret ne descend dans la page', async ({ page }) => {
  await ouvrirLeFormulaire(page);
  await remplir(page, {
    nom: 'Contrôle Page E2E', tel: numeroNeuf(), adresse: 'Rue du Contrôle, Dakar',
  });
  await page.getByRole('button', { name: 'Enregistrer le client' }).click();
  await expect(page.getByTestId('client-cree')).toBeVisible();

  const html = await page.content();
  for (const interdit of ['partner_id', 'session_id=', 'API_KEY', 'freight:',
                          'payload_hash', 'res.partner']) {
    expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
  }
});

test('un visiteur anonyme ne peut pas créer', async ({ page, request }) => {
  await page.goto(`/reception/client/nouveau?consolidation=${DEPART}`);
  await expect(page).toHaveURL(/\/connexion$/);

  const anonyme = await request.post('/api/customers', {
    headers: { 'Content-Type': 'application/json' },
    data: {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      customer_type: 'individual', name: 'Intrus', phone: '+221 77 000 00 00',
      address: 'Nulle part',
    },
  });
  expect(anonyme.status()).toBe(401);
});
