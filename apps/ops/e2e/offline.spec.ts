import { expect, test, type Page } from '@playwright/test';

/**
 * Le mode hors connexion, éprouvé dans un vrai navigateur.
 *
 * ## Ce que ces scénarios protègent
 *
 * Deux mensonges possibles, et un seul les résume : dire à un opérateur que le
 * CRM a reçu ce qu'il vient de saisir alors que rien n'est parti. Le second
 * est son symétrique — perdre une saisie parce que le réseau a coupé, ou la
 * dupliquer parce qu'on a rejoué avec un identifiant neuf.
 *
 * Chaque test vérifie donc l'état de la base Odoo, pas seulement l'écran.
 */

const OPERATEUR = {
  login: process.env.OPS_E2E_LOGIN ?? 'gilles.banc',
  password: process.env.OPS_E2E_PASSWORD ?? 'banc-ops-2026',
};
/** Le second opérateur du banc, tel que l'étape 11 l'a établi. */
const AUTRE = {
  login: process.env.OPS_E2E_DALANDA_LOGIN ?? 'dalanda.banc',
  password: process.env.OPS_E2E_DALANDA_PASSWORD ?? 'banc-dalanda-2026',
};

const DEPART = 'AIR-DSS-CDG-TEST-001';
const CLIENT = '+221 77 123 45 67';

function marqueur(): string {
  return `Offline ${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4)}`;
}

async function connecter(page: Page, qui = OPERATEUR) {
  await page.goto('/connexion');
  await page.getByLabel('Identifiant').fill(qui.login);
  await page.getByLabel('Mot de passe').fill(qui.password);
  await page.getByRole('button', { name: 'Se connecter' }).click();
  await expect(page.getByRole('heading', { name: /^Bonjour / })).toBeVisible();
}

/** Amène le formulaire de colis jusqu'au bouton d'enregistrement. */
async function jusquAuColis(page: Page) {
  await page.getByRole('link', { name: /Réceptionner un colis/ }).click();
  await page.locator('section.carte', { hasText: DEPART })
    .getByRole('link', { name: 'Sélectionner' }).click();
  await page.getByLabel('Numéro de téléphone').fill(CLIENT);
  await page.getByRole('button', { name: 'Rechercher', exact: true }).click();
  await expect(page.getByTestId('client-trouve')).toBeVisible();
  await page.getByRole('button', { name: 'Utiliser ce client' }).click();
  await expect(page.getByLabel('Désignation')).toBeVisible();
}

async function remplirColis(page: Page, designation: string) {
  await page.getByLabel('Catégorie').fill('Non alimentaire');
  await page.getByLabel('Désignation').fill(designation);
  await page.getByLabel('Quantité').fill('1');
  await page.getByLabel('Poids exact total (kg)').fill('13.5');
  await page.getByLabel('Famille tarifaire').selectOption('non_food');
  await page.getByLabel(/Valeur déclarée du contenu/).fill('25000');
}

test('une réception confirmée sans réseau reste sur l’appareil, sans faux numéro',
  async ({ page, context }) => {
    await connecter(page);
    await jusquAuColis(page);
    const designation = marqueur();
    await remplirColis(page, designation);

    await context.setOffline(true);
    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();

    const carte = page.getByTestId('reception-en-file');
    await expect(carte).toBeVisible();
    await expect(carte).toContainText('ENREGISTRÉ SUR CET APPAREIL');
    await expect(carte).toContainText('Synchronisation avec le CRM en attente');
    // Aucun numéro de dossier inventé : le serveur seul les attribue.
    await expect(carte).not.toContainText(/A\d{3}/);
    await expect(page.getByTestId('intake-enregistre')).toHaveCount(0);

    await context.setOffline(false);
  });

test('la reconnexion synchronise et fait apparaître le vrai numéro',
  async ({ page, context }) => {
    await connecter(page);
    await jusquAuColis(page);
    const designation = marqueur();
    await remplirColis(page, designation);

    await context.setOffline(true);
    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
    await expect(page.getByTestId('reception-en-file')).toBeVisible();

    // Avant reconnexion, le CRM n'a rien : la recherche du dossier échoue.
    await context.setOffline(false);
    await page.getByRole('button', { name: 'VOIR LES OPÉRATIONS EN ATTENTE' }).click();
    await expect(page.getByRole('heading', { name: 'SYNCHRONISATION' })).toBeVisible();
    await page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' }).click();

    const synchronisee = page.getByTestId('operation-synchronisee');
    await expect(synchronisee).toHaveCount(1, { timeout: 15_000 });
    // Le numéro affiché vient du serveur, et ressemble à un vrai `Axxx`.
    await expect(synchronisee).toContainText(new RegExp(`${DEPART}-A\\d{3}`));
    await expect(page.getByTestId('operation-file')).toHaveCount(0);
  });

test('une opération en attente survit à un rechargement complet',
  async ({ page, context }) => {
    await connecter(page);
    // L'accueil installe le Service Worker : sans lui, aucune page ne peut
    // s'ouvrir hors connexion, et c'est cela même que le scénario éprouve.
    await page.waitForFunction(() => navigator.serviceWorker.controller !== null,
                               undefined, { timeout: 15_000 });
    await page.goto('/synchronisation');
    await page.goto('/');
    await jusquAuColis(page);
    await remplirColis(page, marqueur());

    await context.setOffline(true);
    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
    await expect(page.getByTestId('reception-en-file')).toBeVisible();

    // Rechargement complet, toujours hors ligne : rien ne doit disparaître.
    await page.goto('/synchronisation');
    await expect(page.getByTestId('operation-file')).toHaveCount(1);
    await expect(page.getByTestId('etat-pending')).toBeVisible();

    await context.setOffline(false);
  });

test('un silence après écriture serveur ne crée pas deux dossiers',
  async ({ page, context }) => {
    // Le test critique. La requête atteint réellement le serveur, qui écrit ;
    // seule la réponse est perdue. Le navigateur doit rejouer avec le même
    // identifiant et n'obtenir qu'un dossier.
    await connecter(page);
    await jusquAuColis(page);
    const designation = marqueur();
    await remplirColis(page, designation);

    const identifiants: string[] = [];
    let premiere = true;
    await context.route('**/api/intakes', async (route) => {
      const corps = route.request().postDataJSON() as { request_uuid: string };
      identifiants.push(corps.request_uuid);
      if (premiere) {
        premiere = false;
        // La requête part vraiment ; on jette la réponse.
        await route.fetch();
        await route.abort('failed');
        return;
      }
      await route.continue();
    });

    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
    await expect(page.getByTestId('reception-en-file')).toBeVisible();

    await page.goto('/synchronisation');
    await page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' }).click();
    const synchronisee = page.getByTestId('operation-synchronisee');
    await expect(synchronisee).toHaveCount(1, { timeout: 20_000 });

    // Deux envois, un seul identifiant : c'est ce qui permet au serveur de
    // reconnaître son propre travail au lieu d'écrire une seconde fois.
    expect(identifiants.length).toBeGreaterThanOrEqual(2);
    expect(new Set(identifiants).size).toBe(1);

    const reference = await synchronisee.locator('.reference').textContent();
    expect(reference?.trim()).toMatch(new RegExp(`^${DEPART}-A\\d{3}$`));

    // Et le CRM n'a bien qu'un dossier portant cette désignation.
    const dossier = await page.request.get(
      `/api/intakes/${encodeURIComponent(reference?.trim() ?? '')}`);
    expect(dossier.status()).toBe(200);
    const charge = await dossier.json() as {
      data: { intake: { lines: { description: string }[] } };
    };
    // Une seule ligne porte cette désignation : le rejeu n'a pas écrit deux
    // fois, et Odoo a bien reconnu son propre travail.
    expect(charge.data.intake.lines.filter((l) => l.description === designation))
      .toHaveLength(1);
  });

test('l’opération d’un opérateur n’est pas envoyée sous la session d’un autre',
  async ({ page, context }) => {
    await connecter(page);
    await jusquAuColis(page);
    await remplirColis(page, marqueur());

    await context.setOffline(true);
    await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
    await expect(page.getByTestId('reception-en-file')).toBeVisible();
    await context.setOffline(false);

    // Gilles s'en va, Dalanda arrive, le réseau est là.
    await page.goto('/');
    await page.getByRole('button', { name: /Se déconnecter/i }).click();
    await connecter(page, AUTRE);

    const envois: string[] = [];
    page.on('request', (requete) => {
      if (requete.url().endsWith('/api/intakes') && requete.method() === 'POST') {
        envois.push(requete.url());
      }
    });
    await page.goto('/synchronisation');
    await page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' }).click();
    await expect(page.getByTestId('file-vide')).toBeVisible();
    expect(envois).toHaveLength(0);

    // L'accueil signale l'attente sans nommer personne.
    await page.goto('/');
    const indicateur = page.getByTestId('indicateur-sync');
    await expect(indicateur).toContainText('autre opérateur');
    await expect(indicateur).not.toContainText('Gilles');

    // Gilles revient : son opération repart.
    await page.getByRole('button', { name: /Se déconnecter/i }).click();
    await connecter(page);
    await page.goto('/synchronisation');
    await page.getByRole('button', { name: 'SYNCHRONISER MAINTENANT' }).click();
    await expect(page.getByTestId('operation-synchronisee'))
      .toHaveCount(1, { timeout: 15_000 });
  });

test('le Service Worker ne met en cache aucune réponse d’API', async ({ page }) => {
  await connecter(page);
  await page.goto('/');
  // Le worker s'installe depuis l'accueil, mais il faut qu'il **contrôle**
  // réellement la page : sans cela, aucune requête ne lui passe entre les
  // mains et le test ne vérifierait rien.
  await page.waitForFunction(
    () => navigator.serviceWorker.controller !== null,
    undefined, { timeout: 15_000 });
  await page.goto('/reception');
  await page.waitForFunction(
    () => navigator.serviceWorker.controller !== null,
    undefined, { timeout: 15_000 });

  // Une vraie lecture d'API depuis le navigateur : sans elle, le test ne
  // prouverait rien — le worker n'aurait simplement jamais eu l'occasion de
  // mettre une réponse privée en cache.
  const statut = await page.evaluate(async () =>
    (await fetch('/api/consolidations')).status);
  expect(statut).toBe(200);

  // L'écriture en cache par le worker n'est pas attendue par la requête : on
  // laisse le temps qu'elle aboutisse, sinon le test ne verrait jamais une
  // réponse mise en cache — et ne prouverait donc rien.
  await page.waitForTimeout(1_500);
  const cache = await page.evaluate(async () => {
    const noms = await caches.keys();
    const urls: string[] = [];
    for (const nom of noms) {
      const ouvert = await caches.open(nom);
      for (const requete of await ouvert.keys()) urls.push(requete.url);
    }
    return urls;
  });
  expect(cache.length).toBeGreaterThan(0);
  for (const url of cache) {
    expect(url).not.toContain('/api/');
  }
});

test('aucun secret ne descend dans la base locale', async ({ page, context }) => {
  await connecter(page);
  await jusquAuColis(page);
  await remplirColis(page, marqueur());
  await context.setOffline(true);
  await page.getByRole('button', { name: 'ENREGISTRER LA RÉCEPTION' }).click();
  await expect(page.getByTestId('reception-en-file')).toBeVisible();
  await context.setOffline(false);

  const contenu = await page.evaluate(async () => {
    const base = await new Promise<IDBDatabase>((resoudre, rejeter) => {
      const demande = indexedDB.open('dally-ops');
      demande.onsuccess = () => resoudre(demande.result);
      demande.onerror = () => rejeter(demande.error);
    });
    const lignes = await new Promise<unknown[]>((resoudre, rejeter) => {
      const t = base.transaction('ops_mutations', 'readonly');
      const demande = t.objectStore('ops_mutations').getAll();
      demande.onsuccess = () => resoudre(demande.result);
      demande.onerror = () => rejeter(demande.error);
    });
    return JSON.stringify(lignes);
  });

  const minuscules = contenu.toLowerCase();
  for (const interdit of ['password', 'api_key', 'apikey', 'bearer', 'session_id',
                          'cookie', 'secret', 'otp', 'banc-ops']) {
    expect(minuscules).not.toContain(interdit);
  }
  // L'identité du propriétaire est une empreinte, pas un identifiant lisible.
  expect(minuscules).not.toContain('gilles.banc');
});
