/**
 * Canaris : chercher des VALEURS, pas des noms de champs.
 *
 * Vérifier qu'un payload ne contient pas la clé `margin` protège contre un seul
 * chemin. Un champ peut être renommé, recopié sous un autre nom, embarqué dans un
 * objet sérialisé, ou transporté par un payload RSC que personne ne relit.
 *
 * La base E2E place donc une valeur unique et improbable dans chaque champ
 * interdit — `DALLY_E2E_SECRET_*`. Si l'une d'elles apparaît quelque part dans ce
 * que le navigateur reçoit, il y a fuite, quel que soit le chemin emprunté.
 *
 * Budget : 1 tentative de connexion.
 */

import { expect, test } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

/** Toutes les valeurs semées dans des champs qu'un client ne doit jamais voir. */
const CANARY_KINDS = [
  'INTERNAL_NOTE', 'SUPPLIER', 'MARGIN', 'SHIPMENT_NOTE',
  'INTERNAL_EVENT', 'EVENT_NOTE', 'DRAFT_PROPOSAL', 'DRAFT_TERMS',
  'UNPUBLISHED_DOC', 'UNPUBLISHED_NAME',
];

const CANARIES = ['A', 'B'].flatMap((tag) =>
  CANARY_KINDS.map((kind) => `DALLY_E2E_SECRET_${kind}_${tag}`),
);

test('aucun canari n’atteint le navigateur, sur aucune surface', async ({ page }) => {
  // Tout ce que le navigateur reçoit : documents HTML, payloads RSC, réponses
  // d'API, fichiers téléchargés. On les accumule et on cherche dedans.
  const received: string[] = [];

  page.on('response', (response) => {
    received.push(response.url());
    void response
      .text()
      .then((text) => received.push(text))
      .catch(() => { /* corps illisible : rien à auditer */ });
  });

  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');

  const paths = [
    '/espace-client',
    '/espace-client/devis',
    '/espace-client/sourcing',
    '/espace-client/trading',
    '/espace-client/expeditions',
    '/espace-client/documents',
    '/espace-client/profil',
  ];

  for (const path of paths) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    received.push(await page.content());
  }

  // Les pages de détail, atteintes par navigation réelle.
  for (const listPath of [
    '/espace-client/devis',
    '/espace-client/sourcing',
    '/espace-client/trading',
    '/espace-client/expeditions',
  ]) {
    await page.goto(listPath);
    const link = page.locator('table tbody tr td:first-child a').first();
    if ((await link.count()) === 0) continue;
    await link.click();
    await page.waitForLoadState('networkidle');
    received.push(await page.content());
  }

  // Le document autorisé : ses octets aussi sont une surface.
  await page.goto('/espace-client/documents');
  const href = await page
    .getByRole('link', { name: /Télécharger/ })
    .first()
    .getAttribute('href');
  if (href) {
    const file = await page.request.get(href);
    received.push(await file.text());
  }

  const haystack = received.join('\n');

  // Contrôle positif : sans lui, un `haystack` vide ferait passer le test.
  expect(haystack.length).toBeGreaterThan(10_000);
  expect(haystack).toContain('E2E Alpha SARL');

  for (const canary of CANARIES) {
    expect(haystack, `canari divulgué : ${canary}`).not.toContain(canary);
  }

  // Le préfixe seul, au cas où une valeur aurait été tronquée en chemin.
  expect(haystack).not.toContain('DALLY_E2E_SECRET');

  // Et les données de l'autre société, par leurs marqueurs propres.
  for (const marker of [
    'E2E Beta SARL', 'E2E Contact B', 'Marchandise synthetique B',
    'Operation synthetique B', 'Colis synthetique B', 'Evenement public B',
    'CONTENU DOCUMENT B',
  ]) {
    expect(haystack, `donnée de B divulguée : ${marker}`).not.toContain(marker);
  }
});
