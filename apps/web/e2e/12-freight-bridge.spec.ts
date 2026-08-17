/**
 * Pont fret de bout en bout : navigateur → Next → Odoo → pont → tk_freight.
 *
 * Le navigateur ne connaît jamais `tk_freight`. Il ouvre des pages
 * DallyTrading, accepte un devis, et voit apparaître une expédition. Toute la
 * chaîne opérationnelle vit derrière, et cette spec vérifie qu'elle y reste.
 *
 * ## Deux dossiers, deux rôles
 *
 * * Les devis `SEA`, `AIR` et `CONC` sont **décidés par le navigateur** : ils
 *   prouvent que l'acceptation provisionne réellement, et que le mode n'est pas
 *   deviné. Ils sont restaurés avant chaque passage.
 * * Un dossier **déjà provisionné et enrichi** porte colis, événements et
 *   documents. Il est lu sans être modifié.
 *
 * Cette séparation n'est pas un raccourci : colis, événements et documents
 * n'existent qu'*après* la création de l'expédition. Les faire naître au milieu
 * du scénario obligerait à interrompre la session pour muter Odoo — la manœuvre
 * exacte qui a déjà produit de faux négatifs sur ce projet.
 *
 * ## Une seule connexion par rôle
 *
 * `/api/portal/auth/login` limite à dix tentatives par IP sur cinq minutes. Une
 * spec qui se connecte à chaque test se freine elle-même : la limite est réelle
 * et documentée, ce n'est pas au test de la contourner. Les deux sessions sont
 * donc ouvertes une fois, puis rejouées par leur état stocké.
 */

import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

const BASE = process.env.E2E_BASE_URL as string;
const ODOO = process.env.E2E_ODOO_URL as string;

/** Dossier enrichi, produit par la graine. */
const DETAIL_REFERENCE = process.env.FREIGHT_DETAIL_REFERENCE as string;
const DETAIL_TOKEN = process.env.FREIGHT_DETAIL_TOKEN as string;
const PUBLISHED_DOCUMENT = process.env.FREIGHT_PUBLISHED_DOCUMENT as string;

/**
 * Chaque devis est reconnu par son **trajet**, qui lui est propre.
 *
 * La liste affiche référence, service, trajet, date et statut — pas la
 * description de la marchandise. Chercher sur une colonne absente ne prouverait
 * qu'une chose : que le test se trompe de page.
 */
const TRAJETS = {
  sea: 'Abidjan',
  air: 'Paris',
  concurrence: 'Banjul',
};

/**
 * Canaris plantés dans les champs internes du dossier opérationnel.
 *
 * Cherchés par leur **valeur**, jamais par un nom de champ : un champ peut être
 * renommé, une projection peut recopier une valeur sous un autre nom, un
 * payload RSC peut transporter un objet entier.
 */
const CANARIES = [
  'DALLY_E2E_SECRET_VENDOR_COST',
  'DALLY_E2E_SECRET_MARGIN',
  'DALLY_E2E_SECRET_SUPPLIER',
  'DALLY_E2E_SECRET_COMMISSION',
  'DALLY_E2E_SECRET_INTERNAL_NOTE',
  'DALLY_E2E_SECRET_INTERNAL_DOCUMENT',
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

async function sessionA(browser: import('@playwright/test').Browser) {
  const contexte = await browser.newContext({ baseURL: BASE, storageState: stateA });
  return { contexte, page: await contexte.newPage() };
}

async function sessionB(browser: import('@playwright/test').Browser) {
  const contexte = await browser.newContext({ baseURL: BASE, storageState: stateB });
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

/**
 * Le mode de transport tel qu'il est **affiché**, à côté du statut.
 *
 * Viser l'élément plutôt que le HTML complet : `page.content()` embarque la
 * charge RSC des pages déjà visitées, et y chercher un libellé reviendrait à
 * interroger l'historique de navigation.
 */
function modeAffiche(page: Page) {
  return page.locator('span.text-sm.text-mist-600').first();
}

/** Références des expéditions listées. */
async function shipmentReferences(page: Page): Promise<string[]> {
  await page.goto('/espace-client/expeditions');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  const links = page.locator('a[href^="/espace-client/expeditions/"]');
  return (await links.allTextContents()).map((t) => t.trim()).filter(Boolean);
}

// ─────────────────────────────────────────────────────────────────────────

test('SEA : accepter un devis fait naître une expédition, visible et persistante', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await sessionA(browser);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.sea);
  expect(await acceptQuote(request, page, reference)).toBe(200);

  const apres = await shipmentReferences(page);
  expect(apres.length, "l'acceptation n'a fait apparaître aucune expédition").toBe(
    avant.length + 1,
  );
  const nouvelle = apres.find((r) => !avant.includes(r)) as string;
  expect(nouvelle).toBeTruthy();

  // ── Le détail est cohérent ──
  await page.goto(`/espace-client/expeditions/${encodeURIComponent(nouvelle)}`);
  await expect(page.getByText(nouvelle).first()).toBeVisible();
  await expect(
    modeAffiche(page),
    'mode maritime absent du détail',
  ).toHaveText(/[Mm]aritime|Sea/);
  assertNoCanary(await page.content(), 'détail SEA');

  // ── Persistance : rechargement, puis retour à la liste ──
  await page.reload();
  await expect(page.getByText(nouvelle).first()).toBeVisible();
  expect(await shipmentReferences(page)).toContain(nouvelle);
  await contexte.close();

  // ── Persistance : session entièrement neuve ──
  //
  // Un contexte neuf, rejouant l'état stocké : aucun cache de navigation ne
  // survit, la donnée est donc bien relue depuis Odoo.
  const rouvert = await sessionA(browser);
  expect(await shipmentReferences(rouvert.page)).toContain(nouvelle);
  await rouvert.contexte.close();
});

test('AIR : le mode vient du service demandé, sans repli maritime', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await sessionA(browser);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.air);
  expect(await acceptQuote(request, page, reference)).toBe(200);

  const apres = await shipmentReferences(page);
  const nouvelle = apres.find((r) => !avant.includes(r)) as string;
  expect(nouvelle, "aucune expédition aérienne n'est apparue").toBeTruthy();

  await page.goto(`/espace-client/expeditions/${encodeURIComponent(nouvelle)}`);

  // Le point de ce test : une version antérieure fixait le mode à « maritime »
  // pour tout le monde. Un client demandant de l'aérien recevait une expédition
  // maritime, sans qu'aucun signal ne l'indique.
  //
  // L'assertion porte sur l'élément affiché, et non sur `page.content()` : le
  // HTML complet embarque la charge RSC de la page précédente — la liste, où
  // figure l'expédition maritime du test précédent. Chercher « Sea » dans tout
  // le document mesurerait donc la navigation, pas le dossier.
  const mode = modeAffiche(page);
  await expect(mode, "le dossier aérien ne porte pas le mode aérien").toHaveText(
    /[Aa]érien|Air/,
  );
  await expect(
    mode,
    'un repli maritime subsiste sur un dossier aérien',
  ).not.toHaveText(/[Mm]aritime|Sea/);
  assertNoCanary(await page.content(), 'détail AIR');
  await contexte.close();
});

test('le détail enrichi montre colis, suivi et document publié — et rien de plus', async ({
  browser,
}) => {
  const { contexte, page } = await sessionA(browser);

  await page.goto(
    `/espace-client/expeditions/${encodeURIComponent(DETAIL_REFERENCE)}`,
  );
  const html = await page.content();

  // ── Contrôle positif : ce qui doit être là l'est ──
  //
  // Sans lui, les absences vérifiées ensuite pourraient n'être que celles d'une
  // page vide.
  expect(html, 'section Colis absente').toMatch(/Colis/);
  expect(html, 'section Suivi absente').toMatch(/Suivi/);
  expect(html, 'événement publié absent').toContain('Chargement effectue');
  expect(html, 'document publié absent').toContain('connaissement-e2e.pdf');

  // ── Ce qui ne doit pas y être ──
  expect(html, 'un événement interne est affiché').not.toContain('Arbitrage interne');
  expect(html, 'le document interne est affiché').not.toContain('arbitrage.pdf');
  assertNoCanary(html, 'détail enrichi (HTML)');

  // ── Le flux RSC porte le même contrat que le HTML ──
  //
  // Demandé séparément : une projection trop large fuiterait par le payload
  // React avant d'apparaître dans le HTML rendu.
  const rsc = await page.request.get(
    `${BASE}/espace-client/expeditions/${encodeURIComponent(DETAIL_REFERENCE)}`,
    { headers: { RSC: '1' } },
  );
  assertNoCanary(await rsc.text(), 'flux RSC du détail');

  // ── Et le JSON du BFF ──
  const me = await page.request.get(`${BASE}/api/portal/me`);
  assertNoCanary(await me.text(), 'réponse JSON du BFF');

  await contexte.close();
});

test('le document publié se télécharge, les autres non', async ({ browser }) => {
  const a = await sessionA(browser);

  const autorise = await a.page.request.get(
    `${BASE}/api/portal/documents/${encodeURIComponent(PUBLISHED_DOCUMENT)}`,
  );
  expect(autorise.status(), 'le document publié doit être téléchargeable').toBe(200);
  const corps = await autorise.text();
  expect(corps).toContain('DALLY_E2E_PUBLISHED_DOCUMENT_BODY');
  assertNoCanary(corps, 'contenu du document téléchargé');
  await a.contexte.close();

  // ── Le même document, pour le client B : refusé ──
  const b = await sessionB(browser);
  const refuse = await b.page.request.get(
    `${BASE}/api/portal/documents/${encodeURIComponent(PUBLISHED_DOCUMENT)}`,
  );
  expect(refuse.status(), 'B a pu télécharger un document de A').toBe(404);
  await b.contexte.close();
});

test('cloisonnement : B ne voit rien de A, et réciproquement', async ({ browser }) => {
  const a = await sessionA(browser);
  const chezA = await shipmentReferences(a.page);
  expect(chezA, 'le dossier enrichi devrait être visible chez A').toContain(
    DETAIL_REFERENCE,
  );
  await a.contexte.close();

  const b = await sessionB(browser);
  const chezB = await shipmentReferences(b.page);
  for (const reference of chezA) {
    expect(chezB, `B voit l'expédition ${reference} de A`).not.toContain(reference);
  }

  // Connaître la référence ne doit rien ouvrir.
  const reponse = await b.page.goto(
    `/espace-client/expeditions/${encodeURIComponent(DETAIL_REFERENCE)}`,
  );
  expect(reponse?.status(), 'B atteint le détail de A par URL directe').toBe(404);
  const html = await b.page.content();
  expect(html).not.toContain('connaissement-e2e.pdf');
  assertNoCanary(html, 'réponse servie à B');
  await b.contexte.close();
});

test('suivi public : le jeton décide, et rien ne distingue invalide d’inconnu', async ({
  request,
}) => {
  // ── Jeton valide : les données autorisées ──
  const valide = await request.get(
    `${BASE}/tracking?ref=${encodeURIComponent(DETAIL_REFERENCE)}&t=${encodeURIComponent(DETAIL_TOKEN)}`,
  );
  expect(valide.status()).toBe(200);
  const corpsValide = await valide.text();
  expect(corpsValide, 'la référence autorisée devrait apparaître').toContain(
    DETAIL_REFERENCE,
  );
  assertNoCanary(corpsValide, 'suivi public autorisé');

  // ── Jeton faux, et référence inconnue ──
  //
  // Ce qui compte n'est pas le code retourné mais son **indiscernabilité** :
  // si une référence existante mal jetonnée se distinguait d'une référence
  // inventée, la paire formerait un oracle d'énumération. La page de suivi
  // répond 200 avec un contenu d'échec, et c'est le contrat existant.
  const mauvaisJeton = await request.get(
    `${BASE}/tracking?ref=${encodeURIComponent(DETAIL_REFERENCE)}&t=jeton-invalide-mais-bien-forme`,
  );
  const inconnue = await request.get(
    `${BASE}/tracking?ref=DT-SHP-2026-999999&t=jeton-invalide-mais-bien-forme`,
  );
  expect(mauvaisJeton.status()).toBe(inconnue.status());

  const corpsMauvais = await mauvaisJeton.text();
  const corpsInconnu = await inconnue.text();
  expect(corpsMauvais, 'un jeton invalide laisse fuir la référence').not.toContain(
    'Chargement effectue',
  );
  expect(corpsInconnu).not.toContain('Chargement effectue');
  assertNoCanary(corpsMauvais, 'suivi avec jeton invalide');

  // La seule différence tolérée entre les deux corps est la référence
  // réaffichée : aucune donnée métier ne doit distinguer les deux cas.
  const neutraliser = (corps: string) =>
    corps.split(DETAIL_REFERENCE).join('REF').split('DT-SHP-2026-999999').join('REF');
  expect(
    neutraliser(corpsMauvais).length,
    'les deux refus diffèrent : oracle d’énumération possible',
  ).toBe(neutraliser(corpsInconnu).length);

  // ── Jeton absent ──
  const sansJeton = await request.get(
    `${BASE}/tracking?ref=${encodeURIComponent(DETAIL_REFERENCE)}`,
  );
  expect(await sansJeton.text()).not.toContain('Chargement effectue');
});

test('les routes natives du fournisseur ne servent aucune donnée', async ({
  request,
}) => {
  // Ces URL sont publiques dans le code source du module, sur GitHub. Retirer
  // un lien d'interface ne les fermerait pas.
  //
  // On ne teste PAS un code particulier : les routes `auth="user"` répondent
  // 200 en servant la page de connexion d'Odoo à un visiteur anonyme, ce qui
  // est le comportement normal du noyau. Ce qui compte est qu'aucune donnée
  // métier ne sorte.
  const routes = [
    '/shipment',
    '/track/shipment',
    '/freight/shipment/booking',
    '/freight/shipment/quotation',
    '/freight/shipment/shipment',
    '/post/comment',
  ];

  for (const route of routes) {
    const reponse = await request.get(`${ODOO}${route}`, { failOnStatusCode: false });
    const corps = await reponse.text();

    expect(corps, `${route} renvoie une page de détail du fournisseur`).not.toContain(
      'Shipment Details',
    );
    expect(corps, `${route} renvoie une référence Dally`).not.toContain(
      DETAIL_REFERENCE,
    );
    expect(corps, `${route} renvoie une référence du fournisseur`).not.toMatch(
      /OCEAN\/\d{4}\/\d{2}\/\d+/,
    );
    assertNoCanary(corps, `route native ${route}`);
  }

  // Le suivi public du fournisseur est la route la plus dangereuse : elle était
  // énumérable sur une référence séquentielle. Elle doit être fermée, pas
  // seulement vide.
  const suivi = await request.get(`${ODOO}/track/shipment`, {
    failOnStatusCode: false,
  });
  expect(suivi.status(), '/track/shipment répond encore').toBe(404);
});

test('idempotence : deux acceptations simultanées ne produisent qu’une chaîne', async ({
  browser,
  request,
}) => {
  const { contexte, page } = await sessionA(browser);

  const avant = await shipmentReferences(page);
  const reference = await quoteReference(page, TRAJETS.concurrence);

  const cookies = await page.context().cookies();
  const jar = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
  const url = `${BASE}/api/portal/quotes/${encodeURIComponent(reference)}/decision`;
  const envoyer = () =>
    request.post(url, {
      headers: { origin: BASE, cookie: jar, 'content-type': 'application/json' },
      data: { decision: 'accept' },
    });

  // Vraiment simultanées : deux appels séquentiels ne testeraient que le rejeu,
  // pas la course. C'est la course qui a révélé que le verrou ne suffisait pas
  // sous REPEATABLE READ.
  const [premiere, seconde] = await Promise.all([envoyer(), envoyer()]);
  expect([premiere.status(), seconde.status()].sort()).toEqual([200, 200]);

  // Une seule expédition apparaît. Le comptage côté base est fait par le
  // harness après la suite : l'interface est paginée et filtrée, elle ne
  // prouverait pas l'absence de doublon côté booking ni côté fournisseur.
  const apres = await shipmentReferences(page);
  const nouvelles = apres.filter((r) => !avant.includes(r));
  expect(
    nouvelles.length,
    'deux acceptations simultanées ont produit plusieurs expéditions',
  ).toBe(1);
  await contexte.close();
});
