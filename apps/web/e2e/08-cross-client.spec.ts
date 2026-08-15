/**
 * Cloisonnement croisé : A contre les références de B, et réciproquement.
 *
 * Les références ne sont pas codées en dur. Chaque client lit les SIENNES depuis
 * ses propres listes, puis l'autre les essaie. C'est ce qui rend le test réel :
 * les références existent vraiment, elles sont valides, et elles doivent
 * néanmoins donner un 404 identique à celui d'une référence inventée.
 *
 * Budget : 2 tentatives de connexion.
 */

import { expect, test, type BrowserContext, type Page } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

interface Refs {
  quote: string;
  sourcing: string;
  trade: string;
  shipment: string;
  document: string;
}

async function firstRef(page: Page, path: string): Promise<string> {
  await page.goto(path);
  const link = page.locator('table tbody tr td:first-child a').first();
  await link.waitFor();
  return ((await link.textContent()) ?? '').trim();
}

/** Ce qu'un client peut voir de lui-même — donc ce que l'autre ne doit pas voir. */
async function collectRefs(context: BrowserContext, account: typeof accounts.portalA) {
  const page = await context.newPage();
  await loginThroughUi(page, account);
  await waitForPath(page, '/espace-client');

  const refs: Refs = {
    quote: await firstRef(page, '/espace-client/devis'),
    sourcing: await firstRef(page, '/espace-client/sourcing'),
    trade: await firstRef(page, '/espace-client/trading'),
    shipment: await firstRef(page, '/espace-client/expeditions'),
    document: '',
  };

  await page.goto('/espace-client/documents');
  const href = await page
    .getByRole('link', { name: /Télécharger/ })
    .first()
    .getAttribute('href');
  refs.document = (href ?? '').replace('/api/portal/documents/', '');

  for (const [key, value] of Object.entries(refs)) {
    expect(value, `référence ${key} introuvable`).toBeTruthy();
  }
  return { page, refs };
}

test('A ne peut atteindre aucune ressource de B, et réciproquement', async ({
  browser,
}) => {
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();

  const { page: pageA, refs: refsA } = await collectRefs(contextA, accounts.portalA);
  const { page: pageB, refs: refsB } = await collectRefs(contextB, accounts.portalB);

  // Les deux jeux doivent être disjoints, sinon le test ne prouverait rien.
  expect(refsA.quote).not.toBe(refsB.quote);
  expect(refsA.shipment).not.toBe(refsB.shipment);

  const sections: Array<[keyof Refs, string]> = [
    ['quote', '/espace-client/devis'],
    ['sourcing', '/espace-client/sourcing'],
    ['trade', '/espace-client/trading'],
    ['shipment', '/espace-client/expeditions'],
  ];

  const OWNERS = {
    A: { tag: 'A', company: 'E2E Alpha SARL', contact: 'E2E Contact A' },
    B: { tag: 'B', company: 'E2E Beta SARL', contact: 'E2E Contact B' },
  } as const;

  for (const [visitor, refs, other] of [
    [pageA, refsB, OWNERS.B],
    [pageB, refsA, OWNERS.A],
  ] as Array<[Page, Refs, (typeof OWNERS)['A']]>) {
    for (const [key, base] of sections) {
      const response = await visitor.goto(`${base}/${encodeURIComponent(refs[key])}`);
      expect(response?.status(), `${base}/${refs[key]}`).toBe(404);

      const html = await visitor.content();
      expect(html).toContain('Dossier introuvable');

      /*
       * On cherche les marqueurs de L'AUTRE société, pas des deux.
       *
       * L'en-tête de navigation affiche la société du VISITEUR sur chaque page,
       * y compris celle-ci — c'est son propre nom, pas une fuite. Une première
       * version interdisait les deux marqueurs et échouait pour cette raison :
       * une assertion trop large qui aurait fini par être relâchée en bloc.
       */
      expect(html).not.toContain(other.company);
      expect(html).not.toContain(other.contact);
      expect(html).not.toContain(`Marchandise synthetique ${other.tag}`);
      expect(html).not.toContain(`Operation synthetique ${other.tag}`);
      expect(html).not.toContain(`Colis synthetique ${other.tag}`);
    }

    // Le document de l'autre : 404 identique, aucun octet.
    const download = await visitor.request.get(
      `/api/portal/documents/${refs.document}`,
    );
    expect(download.status()).toBe(404);
    expect(await download.text()).not.toContain('CONTENU DOCUMENT');
  }

  await contextA.close();
  await contextB.close();
});

test('une référence de B est indistinguable d’une référence inventée', async ({
  page,
}) => {
  /*
   * L'exigence n'est pas « refuser », c'est « refuser de la MÊME façon ».
   *
   * Si une référence valide d'un autre client produisait une réponse même
   * légèrement différente d'une référence inexistante, la différence servirait
   * d'oracle : un attaquant apprendrait quelles références existent.
   */
  await loginThroughUi(page, accounts.portalB);
  await waitForPath(page, '/espace-client');
  const otherClientRef = await firstRef(page, '/espace-client/devis');

  await page.goto('/espace-client/devis');
  const own = await page.locator('table tbody tr td:first-child a').first().textContent();
  expect(own?.trim()).toBe(otherClientRef);

  // On se place maintenant côté A : la référence ci-dessus est celle de B.
  const contextA = await page.context().browser()?.newContext();
  if (!contextA) throw new Error('contexte indisponible');
  const pageA = await contextA.newPage();
  await loginThroughUi(pageA, accounts.portalA);
  await waitForPath(pageA, '/espace-client');

  const real = await pageA.goto(
    `/espace-client/devis/${encodeURIComponent(otherClientRef)}`,
  );
  const realBody = await pageA.content();

  const invented = await pageA.goto('/espace-client/devis/DT-2026-999999');
  const inventedBody = await pageA.content();

  expect(real?.status()).toBe(invented?.status());
  expect(real?.status()).toBe(404);
  // Les deux corps ne diffèrent que par la référence tapée, qui est l'entrée de
  // l'utilisateur lui-même et n'apprend rien sur l'existence du dossier.
  const strip = (html: string) =>
    html.replace(/DT-2026-\d+/g, 'REF').replace(/\s+/g, ' ');
  expect(strip(realBody)).toBe(strip(inventedBody));

  await contextA.close();
});
