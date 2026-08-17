/**
 * Transport de véhicule, de bout en bout dans un vrai navigateur.
 *
 * Le reste de la chaîne est déjà prouvé étage par étage — modèle, API,
 * provisionnement, projections, contrat Zod. Ce qui manquait, et que cette spec
 * seule peut établir : qu'un client remplit réellement le formulaire, que son
 * véhicule apparaît réellement dans son espace, et que rien d'interne ne
 * traverse au passage.
 *
 * ## Deux dossiers, deux rôles
 *
 * * `VehicleSeaA` est décidé par le navigateur et porte les canaris. Il est
 *   restauré avant chaque passage.
 * * `VehicleB` appartient réellement au client B. Il existe pour que le
 *   cloisonnement porte sur une donnée réelle : une référence inventée ne
 *   prouverait que l'absence de cette référence, pas l'existence d'une barrière.
 *
 * ## Une seule connexion par rôle
 *
 * `/api/portal/auth/login` limite à dix tentatives par IP sur cinq minutes. Une
 * spec qui se reconnecte à chaque test se freine elle-même : la limite est
 * réelle et documentée, ce n'est pas au test de la contourner.
 */

import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;
const ODOO = process.env.E2E_ODOO_URL as string;

const VIN_A = process.env.VEHICLE_VIN_A as string;
const VIN_B = process.env.VEHICLE_VIN_B as string;
const REGISTRATION_A = process.env.VEHICLE_REGISTRATION_A as string;

/** VIN saisi par la spec du formulaire public. Le reset le reconnaît. */
const VIN_PUBLIC = 'DALLYE2EVINPUB001';

/**
 * Trajets propres à chaque dossier — la liste affiche le trajet, pas la
 * marchandise.
 *
 * `Bordeaux` et non `Paris` : le devis aérien du pont fret part déjà de Paris,
 * et deux lignes correspondant au même discriminant faisaient échouer sa spec.
 * Un discriminant de fixture doit être unique dans toute la base d'essai.
 */
const TRAJETS = { vehiculeA: 'Bordeaux', vehiculeB: 'Cotonou' };

const CANARIES = [
  'DALLY_E2E_SECRET_VEHICLE_INTERNAL_NOTE',
  'DALLY_E2E_SECRET_VEHICLE_PURCHASE_PRICE',
  // Le prix d'achat est un montant : on le cherche aussi comme nombre, sans
  // quoi la moitié du champ resterait non couverte.
  '987654',
];

function assertNoCanary(payload: string, where: string): void {
  for (const canary of CANARIES) {
    expect(payload, `fuite de ${canary} dans ${where}`).not.toContain(canary);
  }
}

// ─── Sessions partagées ──────────────────────────────────────────────────

let stateA: Awaited<ReturnType<BrowserContext['storageState']>>;
let stateB: Awaited<ReturnType<BrowserContext['storageState']>>;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ browser }) => {
  const ouvrir = async (compte: typeof accounts.portalA) => {
    const contexte = await browser.newContext({ baseURL: BASE });
    const page = await contexte.newPage();
    await loginThroughUi(page, compte);
    await waitForPath(page, '/espace-client');
    const state = await contexte.storageState();
    await contexte.close();
    return state;
  };
  stateA = await ouvrir(accounts.portalA);
  stateB = await ouvrir(accounts.portalB);
});

async function session(browser: Browser, state: typeof stateA) {
  const contexte = await browser.newContext({ baseURL: BASE, storageState: state });
  return { contexte, page: await contexte.newPage() };
}

// ─── Aides ───────────────────────────────────────────────────────────────

/** Référence du devis dont le trajet contient `trajet`. */
async function quoteReference(page: Page, trajet: string): Promise<string> {
  await page.goto('/espace-client/devis');
  const row = page.getByRole('row').filter({ hasText: trajet });
  await expect(row, `devis du trajet « ${trajet} » introuvable`).toHaveCount(1);
  const reference = (await row.getByRole('link').first().textContent())?.trim();
  expect(reference, `référence absente pour ${trajet}`).toBeTruthy();
  return reference as string;
}

async function acceptQuote(
  request: APIRequestContext,
  page: Page,
  reference: string,
): Promise<number> {
  const cookies = await page.context().cookies();
  const jar = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
  const response = await request.post(
    `${BASE}/api/portal/quotes/${encodeURIComponent(reference)}/decision`,
    {
      headers: { origin: BASE, cookie: jar, 'content-type': 'application/json' },
      data: { decision: 'accept' },
    },
  );
  return response.status();
}

async function shipmentReferences(page: Page): Promise<string[]> {
  await page.goto('/espace-client/expeditions');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  const links = page.locator('a[href^="/espace-client/expeditions/"]');
  return (await links.allTextContents()).map((t) => t.trim()).filter(Boolean);
}

/**
 * La section Véhicule telle qu'elle est **affichée**.
 *
 * Viser la section plutôt que `page.content()` : le HTML complet embarque la
 * charge RSC des pages déjà visitées, et y chercher un VIN reviendrait à
 * interroger l'historique de navigation plutôt que la page.
 */
function sectionVehicule(page: Page) {
  return page.locator('section[aria-labelledby="vehicule"]');
}

// ─────────────────────────────────────────────────────────────────────────

test('formulaire public : un véhicule maritime, saisi puis enregistré', async ({
  page,
}) => {
  await page.goto('/devis');

  // Le service est un bouton radio visuellement masqué à l'intérieur d'un
  // label, et son libellé vient de la base — « Vehicle Transport » ici, pas la
  // traduction qu'on pourrait supposer. On vise donc sa VALEUR, qui est stable
  // et indépendante de la langue du catalogue.
  await page
    .locator('input[name="serviceCode"][value="freight_vehicle"]')
    .check({ force: true });

  // Cocher le service ne fait pas avancer le formulaire : il faut valider
  // l'étape. Sans ce clic, les champs de trajet n'existent pas encore dans le
  // DOM, et le remplissage expire sur un élément absent.
  const continuer = page.getByRole('button', { name: /Continuer/i });
  await continuer.click();

  // Trajet.
  await page.getByLabel(/Ville d.origine/i).fill('Paris');
  await page.getByLabel(/Ville de destination/i).fill('Dakar');
  await continuer.click();

  // Étape véhicule : les champs doivent réellement apparaître.
  const vin = page.getByLabel(/Numéro de châssis/i);
  await expect(vin, "les champs véhicule n'apparaissent pas").toBeVisible();

  await page.getByLabel(/^Marque$/i).fill('Peugeot');
  await page.getByLabel(/^Modèle$/i).fill('Partner');
  await page.getByLabel(/^Année$/i).fill('2017');
  await vin.fill(VIN_PUBLIC);
  await page.getByLabel(/Immatriculation/i).fill('E2E-PUB-001');
  await page.getByLabel(/Couleur/i).fill('Bleu');
  await page.getByLabel(/Type de véhicule/i).selectOption('van');
  await page.getByLabel(/État du véhicule/i).selectOption('running');
  await page.getByLabel(/Motorisation/i).selectOption('diesel');
  await page.getByLabel(/Mode de transport/i).selectOption('sea');
  await page.getByLabel(/Nombre de clés/i).fill('2');

  // ── Adresse fantôme : cocher, saisir, décocher ──
  //
  // Le cas réel. Sans nettoyage, l'exploitation recevrait une adresse
  // d'enlèvement pour une prestation qui n'a pas été commandée.
  const enlevement = page.getByLabel(/enlèvement du véhicule/i);
  await enlevement.check();
  const adresse = page.getByLabel(/Adresse d'enlèvement/i);
  await expect(adresse).toBeVisible();
  await adresse.fill('99 rue Fantôme, Paris');
  await enlevement.uncheck();
  await expect(adresse, "l'adresse reste visible après décochage").toBeHidden();

  // Avancer jusqu'à l'étape contact.
  //
  // Le nombre d'étapes dépend du service : le supposer rendrait la spec
  // fragile à tout ajout d'étape. On avance donc jusqu'à ce que le champ de
  // contact apparaisse, avec une borne pour ne jamais boucler indéfiniment.
  const nom = page.getByLabel(/^Nom\b/i).first();
  for (let i = 0; i < 6 && !(await nom.isVisible().catch(() => false)); i += 1) {
    await continuer.click();
  }
  await expect(nom, "l'étape Coordonnées n'a pas été atteinte").toBeVisible();

  await nom.fill('Testeur');
  await page.getByLabel(/E-mail/i).first().fill('vehicule-public@e2e.invalid');

  // Puis jusqu'au bouton d'envoi, qui remplace « Continuer » à la dernière étape.
  const envoyer = page.getByRole('button', { name: /Envoyer ma demande/i });
  for (let i = 0; i < 4 && !(await envoyer.isVisible().catch(() => false)); i += 1) {
    await continuer.click();
  }
  await envoyer.click();

  await expect(
    page.getByText(/reçu|merci|confirmation/i).first(),
    "la confirmation publique n'apparaît pas",
  ).toBeVisible({ timeout: 15_000 });

  // ── La page publique ne doit rien révéler d'interne ──
  const confirmation = await page.content();
  expect(confirmation, 'le VIN complet apparaît sur la page publique').not.toContain(
    VIN_PUBLIC,
  );
  assertNoCanary(confirmation, 'confirmation publique');
});

test('portail A : le véhicule de son devis, VIN complet et libellés français', async ({
  browser,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const reference = await quoteReference(page, TRAJETS.vehiculeA);
  await page.goto(`/espace-client/devis/${encodeURIComponent(reference)}`);

  const section = sectionVehicule(page);
  await expect(section, 'section Véhicule absente').toBeVisible();

  const texte = (await section.innerText()).replace(/\s+/g, ' ');
  expect(texte).toContain('Toyota');
  expect(texte).toContain('Land Cruiser');
  expect(texte).toContain('2018');
  expect(texte, 'le VIN du propriétaire devrait être visible').toContain(VIN_A);
  expect(texte).toContain(REGISTRATION_A);
  // Libellés client, jamais les codes internes.
  expect(texte).toContain('Maritime');
  expect(texte).toContain('Roulant');
  expect(texte).not.toContain('freight_vehicle');
  expect(texte).not.toMatch(/\bsea\b/);

  // ── Rien d'interne, ni dans le rendu ni dans le flux React ──
  assertNoCanary(await page.content(), 'détail devis (HTML)');
  const rsc = await page.request.get(
    `${BASE}/espace-client/devis/${encodeURIComponent(reference)}`,
    { headers: { RSC: '1' } },
  );
  assertNoCanary(await rsc.text(), 'détail devis (RSC)');
  assertNoCanary(await (await page.request.get(`${BASE}/api/portal/me`)).text(), 'BFF');

  await contexte.close();
});

test('acceptation : la chaîne fret naît, et le véhicule y est rattaché', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.vehiculeA);
  expect(await acceptQuote(request, page, reference)).toBe(200);

  const apres = await shipmentReferences(page);
  expect(apres.length, "l'acceptation n'a produit aucune expédition").toBe(
    avant.length + 1,
  );
  const nouvelle = apres.find((r) => !avant.includes(r)) as string;
  expect(nouvelle).toBeTruthy();

  // ── Le détail porte le véhicule transporté ──
  await page.goto(`/espace-client/expeditions/${encodeURIComponent(nouvelle)}`);
  const section = sectionVehicule(page);
  await expect(section, 'section Véhicule transporté absente').toBeVisible();

  const texte = (await section.innerText()).replace(/\s+/g, ' ');
  expect(texte).toContain(VIN_A);
  expect(texte).toContain('Toyota');
  expect(texte).toContain('Maritime');

  // ── Les sections du pont fret restent en place ──
  const html = await page.content();
  expect(html, 'section Colis disparue').toMatch(/Colis/);
  expect(html, 'section Suivi disparue').toMatch(/Suivi/);
  expect(html, 'section Documents disparue').toMatch(/Documents/);
  assertNoCanary(html, 'détail expédition');

  // ── Persistance : rechargement, puis session entièrement neuve ──
  await page.reload();
  await expect(sectionVehicule(page)).toBeVisible();
  await contexte.close();

  const rouvert = await session(browser, stateA);
  await rouvert.page.goto(
    `/espace-client/expeditions/${encodeURIComponent(nouvelle)}`,
  );
  const apresReconnexion = (await sectionVehicule(rouvert.page).innerText()).replace(
    /\s+/g,
    ' ',
  );
  expect(apresReconnexion, 'le véhicule a disparu après reconnexion').toContain(VIN_A);
  await rouvert.contexte.close();
});

test('idempotence : rejouer la décision ne duplique rien à l’écran', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.vehiculeA);
  // Le devis est déjà accepté par le test précédent : la décision doit être
  // relue, pas rejouée. Le comptage en base est fait par le harness.
  expect(await acceptQuote(request, page, reference)).toBe(200);

  expect(
    (await shipmentReferences(page)).length,
    'le rejeu a produit une seconde expédition',
  ).toBe(avant.length);
  await contexte.close();
});

test('cloisonnement : B ne voit rien du véhicule de A, et réciproquement', async ({
  browser,
}) => {
  const a = await session(browser, stateA);
  const referenceA = await quoteReference(a.page, TRAJETS.vehiculeA);
  const expeditionsA = await shipmentReferences(a.page);

  // A ne doit pas atteindre le dossier véhicule de B, qui existe réellement.
  const chezA = await a.page.goto('/espace-client/devis');
  expect(chezA?.status()).toBe(200);
  const listeA = await a.page.content();
  expect(listeA, 'A voit le véhicule de B').not.toContain(VIN_B);
  // Le VIN ne doit pas non plus figurer dans sa propre liste.
  expect(listeA, 'le VIN apparaît dans la liste des devis').not.toContain(VIN_A);
  await a.contexte.close();

  const b = await session(browser, stateB);
  const devisB = await b.page.goto(
    `/espace-client/devis/${encodeURIComponent(referenceA)}`,
  );
  expect(devisB?.status(), 'B atteint le devis de A').toBe(404);
  expect(await b.page.content(), 'le VIN de A fuit vers B').not.toContain(VIN_A);

  for (const reference of expeditionsA) {
    const reponse = await b.page.goto(
      `/espace-client/expeditions/${encodeURIComponent(reference)}`,
    );
    expect(reponse?.status(), `B atteint l'expédition ${reference} de A`).toBe(404);
    expect(await b.page.content()).not.toContain(VIN_A);
  }
  await b.contexte.close();
});

test('suivi public : ni VIN, ni immatriculation, ni canari', async ({
  browser,
  request,
}) => {
  const a = await session(browser, stateA);
  const expeditions = await shipmentReferences(a.page);
  expect(expeditions.length).toBeGreaterThan(0);
  await a.contexte.close();

  // Le suivi public est atteint sans session : c'est bien la surface publique
  // qui est mesurée, pas une page authentifiée.
  for (const reference of expeditions) {
    const reponse = await request.get(
      `${BASE}/tracking?ref=${encodeURIComponent(reference)}`,
    );
    const corps = await reponse.text();
    expect(corps, 'le VIN apparaît dans le suivi public').not.toContain(VIN_A);
    expect(corps, "l'immatriculation apparaît dans le suivi public").not.toContain(
      REGISTRATION_A,
    );
    assertNoCanary(corps, `suivi public de ${reference}`);
  }
});

test('la route de suivi native du fournisseur reste fermée', async ({ request }) => {
  const reponse = await request.get(`${ODOO}/track/shipment`, {
    failOnStatusCode: false,
  });
  expect(reponse.status(), '/track/shipment répond encore').toBe(404);

  const corps = await reponse.text();
  expect(corps).not.toContain(VIN_A);
  assertNoCanary(corps, 'route native tk');
});
