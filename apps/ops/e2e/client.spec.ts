import { expect, test, type Page } from '@playwright/test';

/**
 * Retrouver un client au comptoir, de bout en bout.
 *
 * Le banc contient trois fiches : une seule au +221 77 123 45 67, deux au
 * +221 76 000 00 00, et rien au +221 77 999 88 77. Les trois issues de la
 * recherche sont donc jouées contre un vrai Odoo.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const UNIQUE = '+221 77 123 45 67';
const AMBIGU = '+221 76 000 00 00';
const INCONNU = '+221 77 999 88 77';

async function ouvrirLIdentification(page: Page) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(OPERATEUR.login);
  await page.getByLabel('Mot de passe').fill(OPERATEUR.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: 'Bonjour Gilles' })).toBeVisible();

  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await expect(page.getByRole('heading', { name: 'Identifier le client' })).toBeVisible();
}

async function chercher(page: Page, numero: string) {
  await page.getByLabel('Numéro de téléphone').fill(numero);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
}

test('l’écran d’identification rappelle le départ choisi', async ({ page }) => {
  await ouvrirLIdentification(page);
  await expect(page.getByText(DEPART)).toBeVisible();
  await expect(page.getByText('Dakar → Paris')).toBeVisible();
});

test('aucun champ « nom » n’est proposé', async ({ page }) => {
  await ouvrirLIdentification(page);
  await expect(page.locator('input[name="name"]')).toHaveCount(0);
  await expect(page.getByRole('link', { name: /par nom/ })).toHaveCount(0);
});

test('un numéro connu identifie le client et mène à l’étape suivante', async ({ page }) => {
  await ouvrirLIdentification(page);
  await chercher(page, UNIQUE);

  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await expect(page.getByText('Aissatou Kandji')).toBeVisible();
  await expect(page.getByText('207 rue Saint-Charles, 75015 Paris, France')).toBeVisible();

  await page.getByRole('button', { name: 'Utiliser ce client' }).click();
  await expect(page.getByRole('heading', { name: 'Détail du colis' })).toBeVisible();
  await expect(page.getByTestId('consolidation-selectionnee')).toHaveText(DEPART);
});

test('seule une référence opaque voyage dans l’URL', async ({ page }) => {
  await ouvrirLIdentification(page);
  await chercher(page, UNIQUE);
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();
  await expect(page.getByRole('heading', { name: 'Détail du colis' })).toBeVisible();

  const url = page.url();
  // Ni nom, ni téléphone, ni adresse, ni identifiant Odoo.
  for (const interdit of ['Aissatou', 'Kandji', '771234567', '77%20123', 'partner_id',
                          'aissatou.kandji@example.test', 'Saint-Charles']) {
    expect(url).not.toContain(interdit);
  }
  expect(url).toMatch(
    /customer=[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/);
});

test('« ce n’est pas le bon client » revient au formulaire sans rien changer', async ({ page }) => {
  await ouvrirLIdentification(page);
  await chercher(page, UNIQUE);
  await expect(page.getByTestId('client-trouve')).toBeVisible();

  await page.getByRole('button', { name: 'Ce n’est pas le bon client' }).click();
  await expect(page.getByLabel('Numéro de téléphone')).toBeVisible();
  await expect(page.getByTestId('client-trouve')).toHaveCount(0);
});

test('un numéro inconnu propose la création, sans erreur', async ({ page }) => {
  await ouvrirLIdentification(page);
  await chercher(page, INCONNU);

  await expect(page.getByTestId('introuvable')).toBeVisible();
  await expect(page.getByText('Aucun client trouvé.')).toBeVisible();
  await page.getByRole('button', { name: 'Créer un nouveau client' }).click();
  await expect(page.getByRole('heading', { name: 'Nouveau client' })).toBeVisible();
});

test('un numéro ambigu n’affiche aucune identité', async ({ page }) => {
  await ouvrirLIdentification(page);
  await chercher(page, AMBIGU);

  await expect(page.getByTestId('ambigu')).toBeVisible();
  await expect(page.getByText('Plusieurs fiches correspondent')).toBeVisible();

  const html = await page.content();
  // Montrer la première de deux exposerait quelqu'un qui n'est pas au comptoir.
  for (const interdit of ['Konaté', 'Mamadou', 'Mariama', 'mk@example.test',
                          'mrk@example.test']) {
    expect(html).not.toContain(interdit);
  }
  await expect(page.getByRole('button', { name: 'Utiliser ce client' })).toHaveCount(0);
});

test('un numéro trop court n’est jamais envoyé au serveur', async ({ page }) => {
  await ouvrirLIdentification(page);

  const envois: string[] = [];
  page.on('request', (requete) => {
    if (requete.url().includes('/api/customers/search')) envois.push(requete.url());
  });

  await chercher(page, '77');
  // `p[role="alert"]` et non `getByRole('alert')` : Next place son propre
  // annonceur de route sous ce rôle.
  await expect(page.locator('p[role="alert"]')).toContainText('9 chiffres au minimum');
  expect(envois).toHaveLength(0);
});

test('la recherche par e-mail est disponible en second choix', async ({ page }) => {
  await ouvrirLIdentification(page);
  await page.getByRole('button', { name: 'Rechercher par e-mail' }).click();

  await page.getByLabel('Adresse e-mail').fill('aissatou.kandji@example.test');
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByText('Aissatou Kandji')).toBeVisible();
});

test('le numéro ne voyage jamais dans une URL', async ({ page }) => {
  const urls: string[] = [];
  page.on('request', (requete) => urls.push(requete.url()));

  await ouvrirLIdentification(page);
  await chercher(page, UNIQUE);
  await expect(page.getByTestId('client-trouve')).toBeVisible();

  // Un numéro placé en chaîne de requête finirait dans l'historique du
  // navigateur et dans les journaux du proxy.
  for (const url of urls) {
    expect(url).not.toContain('771234567');
    expect(url).not.toContain('77+123');
    expect(url).not.toContain('%2B221');
  }
});

test('aucun identifiant Odoo ni secret ne descend dans la page', async ({ page }) => {
  await ouvrirLIdentification(page);
  await chercher(page, UNIQUE);
  await expect(page.getByTestId('client-trouve')).toBeVisible();

  const html = await page.content();
  for (const interdit of ['partner_id', 'session_id=', 'API_KEY', 'freight:',
                          'credit', 'balance', 'res.partner']) {
    expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
  }
});

test('un visiteur anonyme ne peut pas chercher', async ({ page, request }) => {
  await page.goto(`/reception/client?consolidation=${DEPART}`);
  await expect(page).toHaveURL(/\/connexion$/);

  const anonyme = await request.post('/api/customers/search', {
    headers: { 'Content-Type': 'application/json' },
    data: { phone: '+221 77 123 45 67' },
  });
  expect(anonyme.status()).toBe(401);
});
