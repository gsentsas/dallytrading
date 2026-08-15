/**
 * Audit du trafic réseau réel du navigateur.
 *
 * Un test unitaire vérifie ce que le code envoie ; celui-ci vérifie ce qui passe
 * effectivement sur le fil, y compris ce que Next ajoute de son côté (payloads
 * RSC, préchargements, en-têtes de framework).
 *
 * Budget : 1 tentative de connexion.
 */

import { expect, test } from '@playwright/test';

import { accounts, loginThroughUi, waitForPath } from './fixtures';

interface Exchange {
  readonly url: string;
  readonly method: string;
  readonly headers: string;
  readonly body: string;
  /** Rempli après coup : voir la note sur la capture, plus bas. */
  response: string;
}

test('rien de sensible ne circule, hors le mot de passe dans la seule requête de connexion', async ({
  page,
}) => {
  const exchanges: Exchange[] = [];

  /*
   * L'échange est enregistré SYNCHRONEMENT, et le corps de réponse rempli après.
   *
   * La première version attendait `response.text()` avant d'enregistrer quoi que
   * ce soit. Or la réponse de connexion est immédiatement suivie d'une navigation
   * dure : la lecture de son corps ne se résout jamais, et l'échange le plus
   * important de l'audit — celui qui porte le mot de passe — n'était tout
   * simplement pas capturé. Le test passait alors en n'ayant rien examiné.
   */
  page.on('response', (response) => {
    const request = response.request();
    const exchange: Exchange = {
      url: request.url(),
      method: request.method(),
      headers: JSON.stringify(request.headers()),
      body: request.postData() ?? '',
      response: '',
    };
    exchanges.push(exchange);
    void response
      .text()
      .then((text) => { exchange.response = text; })
      .catch(() => { /* corps devenu illisible : rien à auditer */ });
  });

  await loginThroughUi(page, accounts.portalA);
  await waitForPath(page, '/espace-client');
  await page.reload();
  await page.waitForLoadState('networkidle');

  expect(exchanges.length).toBeGreaterThan(3);

  // Garde-fou : sans cet échange, tout ce qui suit examinerait le vide.
  const loginExchanges = exchanges.filter(
    (exchange) => new URL(exchange.url).pathname === '/api/portal/auth/login',
  );
  expect(loginExchanges, 'la requête de connexion doit avoir été capturée').toHaveLength(1);

  const secret = process.env.E2E_PORTAL_SECRET as string;
  const password = accounts.portalA.password();

  for (const exchange of exchanges) {
    const everything = [
      exchange.url, exchange.headers, exchange.body, exchange.response,
    ].join('\n');

    // Le secret de scellement ne quitte jamais le serveur.
    expect(everything).not.toContain(secret);
    // Aucun en-tête d'authentification de service ne part vers le navigateur.
    expect(exchange.headers.toLowerCase()).not.toContain('x-api-key');
    expect(exchange.headers.toLowerCase()).not.toContain('authorization');
    // L'identifiant de session Odoo reste côté serveur : le navigateur ne
    // détient que le cookie scellé, qu'il ne peut pas ouvrir.
    expect(everything).not.toContain('session_id=');
    // Aucune donnée d'un autre client.
    expect(everything).not.toContain('E2E Beta SARL');
    expect(everything).not.toContain('E2E Contact B');
  }

  /*
   * Le mot de passe n'apparaît qu'une fois : dans le corps du POST de connexion.
   *
   * C'est le seul endroit légitime — il faut bien le transmettre. Ce qui compte
   * est qu'il ne réapparaisse ni dans une URL, ni dans un en-tête, ni dans une
   * réponse, ni dans un payload RSC rendu ensuite.
   */
  const carryingPassword = exchanges.filter((exchange) =>
    [exchange.url, exchange.headers, exchange.response].join('\n').includes(password),
  );
  expect(carryingPassword).toHaveLength(0);

  const inBody = exchanges.filter((exchange) => exchange.body.includes(password));
  expect(inBody).toHaveLength(1);
  expect(inBody[0]?.method).toBe('POST');
  expect(new URL(inBody[0]?.url as string).pathname).toBe('/api/portal/auth/login');
});
