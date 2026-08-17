/**
 * Groupage maritime et aérien, de bout en bout dans un vrai navigateur.
 *
 * Le risque central du chantier est la confusion entre le service et le mode
 * physique. Les deux modes sont donc validés dans Chrome — pas seulement le
 * maritime : c'est précisément l'aérien qui, mal projeté, serait facturé au
 * ratio maritime et coûterait six fois trop cher au client.
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

/** Trajets uniques dans toute la base d'essai — voir la graine. */
const TRAJETS = {
  sea: 'Ouagadougou',
  air: 'Bamako',
  clientB: 'Niamey',
};

const CANARIES = [
  'DALLY_E2E_SECRET_GROUPAGE_INTERNAL_NOTE',
  // Le taux interne est un montant : cherché comme nombre, un `Monetary` ne
  // pouvant pas porter de marqueur textuel.
  '876543',
];

function assertNoCanary(payload: string, where: string): void {
  for (const canary of CANARIES) {
    expect(payload, `fuite de ${canary} dans ${where}`).not.toContain(canary);
  }
}

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

async function quoteReference(page: Page, trajet: string): Promise<string> {
  await page.goto('/espace-client/devis');
  const row = page.getByRole('row').filter({ hasText: trajet });
  await expect(row, `devis du trajet « ${trajet} » introuvable`).toHaveCount(1);
  const reference = (await row.getByRole('link').first().textContent())?.trim();
  expect(reference).toBeTruthy();
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
 * Texte visible de la page courante.
 *
 * `body.innerText` plutôt que `page.content()` : le HTML complet embarque la
 * charge RSC des pages déjà visitées, et y chercher un libellé reviendrait à
 * interroger l'historique de navigation. `innerText` ne rend que ce qui est
 * réellement affiché.
 *
 * Et `body` plutôt que `main` : le sélecteur `main` s'est révélé fragile — la
 * page n'en expose pas toujours un seul, et l'attente expirait.
 */
async function texteVisible(page: Page): Promise<string> {
  return (await page.locator('body').innerText()).replace(/\s+/g, ' ');
}

// ─────────────────────────────────────────────────────────────────────────

test('formulaire public : le mode de groupage est exigé et transmis', async ({
  page,
}) => {
  await page.goto('/devis');
  await page
    .locator('input[name="serviceCode"][value="freight_groupage"]')
    .check({ force: true });

  const continuer = page.getByRole('button', { name: /Continuer/i });
  await continuer.click();

  await page.getByLabel(/Ville d.origine/i).fill('Douala');
  await page.getByLabel(/Ville de destination/i).fill('Lyon');
  await continuer.click();

  // Le champ doit réellement apparaître pour ce service.
  const mode = page.getByLabel(/Mode de transport/i);
  await expect(mode, "le choix du mode de groupage n'apparaît pas").toBeVisible();

  // Les deux options existent, et aucune n'est présélectionnée : deviner serait
  // exactement ce que ce champ existe pour empêcher.
  await expect(mode).toHaveValue('');
  await mode.selectOption('air');

  await page.getByLabel(/Nature de la marchandise/i).fill('Textile leger');
  await continuer.click();

  const nom = page.getByLabel(/^Nom\b/i).first();
  for (let i = 0; i < 6 && !(await nom.isVisible().catch(() => false)); i += 1) {
    await continuer.click();
  }
  await expect(nom, "l'étape Coordonnées n'a pas été atteinte").toBeVisible();
  await nom.fill('Testeur');
  await page.getByLabel(/E-mail/i).first().fill('groupage-public@e2e.invalid');

  const envoyer = page.getByRole('button', { name: /Envoyer ma demande/i });
  for (let i = 0; i < 4 && !(await envoyer.isVisible().catch(() => false)); i += 1) {
    await continuer.click();
  }
  await envoyer.click();

  await expect(
    page.getByText(/reçu|merci|confirmation/i).first(),
    "la confirmation publique n'apparaît pas",
  ).toBeVisible({ timeout: 15_000 });
  assertNoCanary(await page.content(), 'confirmation publique');
});

test('portail : le devis maritime affiche son mode, sans canari', async ({
  browser,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const reference = await quoteReference(page, TRAJETS.sea);
  await page.goto(`/espace-client/devis/${encodeURIComponent(reference)}`);

  await expect(
    page.getByText('Groupage maritime').first(),
    'le mode de groupage maritime est absent de la page',
  ).toBeVisible();

  // Le MODE doit être un libellé, jamais son code technique. C'est ce que ce
  // cycle possède.
  //
  // Le code de service (`freight_groupage`) apparaît par ailleurs sur cette
  // page, via `<Detail label="Service" value={quote.service} />` : c'est un
  // affichage antérieur, commun à tous les services, et le corriger demanderait
  // d'ajouter un libellé de service au contrat portail. Hors périmètre ici, mais
  // consigné.
  const contenu = await texteVisible(page);
  expect(contenu, 'le mode est affiché en code brut').not.toMatch(
    /Mode de groupage\s*:?\s*(sea|air)\b/i,
  );

  assertNoCanary(await page.content(), 'détail devis maritime (HTML)');
  const rsc = await page.request.get(
    `${BASE}/espace-client/devis/${encodeURIComponent(reference)}`,
    { headers: { RSC: '1' } },
  );
  assertNoCanary(await rsc.text(), 'détail devis maritime (RSC)');
  await contexte.close();
});

test('groupage MARITIME : acceptation puis expédition maritime', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.sea);
  expect(await acceptQuote(request, page, reference)).toBe(200);

  const apres = await shipmentReferences(page);
  expect(apres.length).toBe(avant.length + 1);
  const nouvelle = apres.find((r) => !avant.includes(r)) as string;

  await page.goto(`/espace-client/expeditions/${encodeURIComponent(nouvelle)}`);
  const entete = await texteVisible(page);
  expect(entete, 'le type d’envoi Groupage est absent').toContain('Groupage');
  expect(entete, 'le mode maritime est absent').toMatch(/Sea|[Mm]aritime/);

  assertNoCanary(await page.content(), 'détail expédition maritime');
  await contexte.close();
});

test('groupage AÉRIEN : jamais ramené au maritime', async ({ browser, request }) => {
  const { contexte, page } = await session(browser, stateA);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.air);
  expect(await acceptQuote(request, page, reference)).toBe(200);

  const apres = await shipmentReferences(page);
  const nouvelle = apres.find((r) => !avant.includes(r)) as string;
  expect(nouvelle, "aucune expédition aérienne n'est apparue").toBeTruthy();

  await page.goto(`/espace-client/expeditions/${encodeURIComponent(nouvelle)}`);
  const entete = await texteVisible(page);

  // Le cœur du chantier : les deux notions coexistent, et le mode est aérien.
  expect(entete, 'le type d’envoi Groupage est absent').toContain('Groupage');
  expect(entete, 'le mode aérien est absent').toMatch(/Air|[Aa]érien/);
  expect(entete, 'un groupage aérien est présenté comme maritime').not.toMatch(
    /Sea Freight|Fret maritime/,
  );

  assertNoCanary(await page.content(), 'détail expédition aérienne');
  await contexte.close();
});

test('idempotence : rejouer la décision ne duplique pas l’expédition', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.sea);
  expect(await acceptQuote(request, page, reference)).toBe(200);

  expect(
    (await shipmentReferences(page)).length,
    'le rejeu a produit une seconde expédition',
  ).toBe(avant.length);
  await contexte.close();
});

test('concurrence : deux acceptations simultanées, une seule chaîne', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await session(browser, stateA);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.air);

  const cookies = await page.context().cookies();
  const jar = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
  const url = `${BASE}/api/portal/quotes/${encodeURIComponent(reference)}/decision`;
  const envoyer = () =>
    request.post(url, {
      headers: { origin: BASE, cookie: jar, 'content-type': 'application/json' },
      data: { decision: 'accept' },
    });

  // Vraiment simultanées : deux appels séquentiels ne testeraient que le rejeu.
  const [premiere, seconde] = await Promise.all([envoyer(), envoyer()]);
  expect([premiere.status(), seconde.status()].sort()).toEqual([200, 200]);

  const nouvelles = (await shipmentReferences(page)).filter(
    (r) => !avant.includes(r),
  );
  expect(nouvelles.length, 'la course a produit plusieurs expéditions').toBeLessThanOrEqual(1);
  await contexte.close();
});

test('cloisonnement : B ne voit rien du groupage de A', async ({ browser }) => {
  const a = await session(browser, stateA);
  const referenceA = await quoteReference(a.page, TRAJETS.sea);
  const expeditionsA = await shipmentReferences(a.page);

  // A ne doit pas atteindre le dossier groupage de B, qui existe réellement.
  const listeA = await a.page.content();
  expect(listeA, 'A voit le trajet du dossier de B').not.toContain(TRAJETS.clientB);
  await a.contexte.close();

  const b = await session(browser, stateB);
  const devis = await b.page.goto(
    `/espace-client/devis/${encodeURIComponent(referenceA)}`,
  );
  expect(devis?.status(), 'B atteint le devis de A').toBe(404);
  assertNoCanary(await b.page.content(), 'réponse servie à B');

  for (const reference of expeditionsA) {
    const reponse = await b.page.goto(
      `/espace-client/expeditions/${encodeURIComponent(reference)}`,
    );
    expect(reponse?.status(), `B atteint l'expédition ${reference}`).toBe(404);
  }
  await b.contexte.close();
});

test('suivi public et route native : rien ne fuit', async ({ browser, request }) => {
  const a = await session(browser, stateA);
  const expeditions = await shipmentReferences(a.page);
  await a.contexte.close();

  for (const reference of expeditions) {
    const corps = await (
      await request.get(`${BASE}/tracking?ref=${encodeURIComponent(reference)}`)
    ).text();
    assertNoCanary(corps, `suivi public de ${reference}`);
  }

  const native = await request.get(`${ODOO}/track/shipment`, {
    failOnStatusCode: false,
  });
  expect(native.status(), '/track/shipment répond encore').toBe(404);
  assertNoCanary(await native.text(), 'route native tk');
});
