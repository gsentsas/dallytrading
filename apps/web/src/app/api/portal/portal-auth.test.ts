/**
 * Tests de bout en bout de la frontière d'authentification, à travers les Route
 * Handlers réels.
 *
 * Seuls deux éléments sont simulés : `fetch` (Odoo n'est pas joignable en test) et
 * `next/headers` (le magasin de cookies appartient au runtime Next). Tout le reste
 * — scellement, contrôle d'origine, limitation de débit, DAL — est le code de
 * production. Simuler la DAL rendrait les tests verts sans rien prouver de la
 * chaîne qu'ils sont censés valider.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { resetRateLimits } from '@/lib/rate-limit';
import {
  PORTAL_COOKIE,
  sealSession,
  unsealSession,
} from '@/lib/portal/session';

const SITE = 'https://dallytrading.com';
const SECRET = 'p'.repeat(48);
const ODOO_SESSION = 'odoosession1234567890';

/** Magasin de cookies minimal, fidèle à l'API utilisée par le code. */
class CookieJar {
  private readonly store = new Map<string, string>();

  get(name: string) {
    const value = this.store.get(name);
    return value === undefined ? undefined : { name, value };
  }

  set(name: string, value: string, _options?: unknown) {
    this.store.set(name, value);
  }

  raw(name: string) {
    return this.store.get(name);
  }

  seed(value: string) {
    this.store.set(PORTAL_COOKIE, value);
  }
}

let jar: CookieJar;
let fetchMock: ReturnType<typeof vi.fn>;

vi.mock('next/headers', () => ({
  cookies: async () => jar,
}));

function json(body: unknown, init: { status?: number; setCookie?: string } = {}) {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  if (init.setCookie) headers.append('set-cookie', init.setCookie);
  return new Response(JSON.stringify(body), { status: init.status ?? 200, headers });
}

const AUTH_OK = () =>
  json({ result: { uid: 12 } }, { setCookie: `session_id=${ODOO_SESSION}; HttpOnly` });

const ME_OK = () =>
  json({
    success: true,
    data: {
      name: 'Client Test',
      email: 'client@example.com',
      phone: null,
      company: 'Client SARL',
      city: 'Dakar',
      country: 'Sénégal',
    },
  });

function loginRequest(
  body: unknown,
  headers: Record<string, string> = { origin: SITE },
): Request {
  return new Request(`${SITE}/api/portal/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

const CREDENTIALS = { login: 'client@example.com', password: 'un-mot-de-passe' };

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ODOO_URL = 'https://crm.example.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'k'.repeat(32);
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = SECRET;
  resetServerEnvCache();
  resetRateLimits();
  jar = new CookieJar();
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function importLogin() {
  return (await import('./auth/login/route')).POST;
}
async function importLogout() {
  return (await import('./auth/logout/route')).POST;
}
async function importMe() {
  return (await import('./me/route')).GET;
}

describe('POST /api/portal/auth/login', () => {
  it('établit la session sur des identifiants valides', async () => {
    fetchMock.mockResolvedValueOnce(AUTH_OK()).mockResolvedValueOnce(ME_OK());

    const response = await (await importLogin())(loginRequest(CREDENTIALS));
    expect(response.status).toBe(200);

    const body = await response.json();
    expect(body.data).toEqual({ name: 'Client Test', company: 'Client SARL' });

    // Le cookie contient bien la session Odoo, et seulement scellée.
    const cookie = jar.raw(PORTAL_COOKIE);
    expect(cookie).toBeDefined();
    expect(cookie).not.toContain(ODOO_SESSION);
    expect(unsealSession(cookie as string, SECRET).odooSessionId).toBe(ODOO_SESSION);
  });

  it('ne renvoie aucune donnée métier dans le DTO', async () => {
    fetchMock.mockResolvedValueOnce(AUTH_OK()).mockResolvedValueOnce(ME_OK());
    const body = await (await (await importLogin())(loginRequest(CREDENTIALS))).json();
    // L'e-mail et le pays existent côté Odoo mais n'ont rien à faire dans la
    // réponse de connexion : le navigateur n'en a pas besoin pour afficher un nom.
    expect(Object.keys(body.data)).toEqual(['name', 'company']);
  });

  it('refuse des identifiants faux sans poser de cookie', async () => {
    fetchMock.mockResolvedValueOnce(json({ result: { uid: false } }));

    const response = await (await importLogin())(loginRequest(CREDENTIALS));
    expect(response.status).toBe(401);
    expect(jar.raw(PORTAL_COOKIE)).toBeUndefined();
  });

  it('refuse un compte interne et referme la session Odoo ouverte', async () => {
    // Odoo authentifie le salarié — c'est /api/v1/portal/me, réservé aux comptes
    // `share`, qui refuse. Sans ce second appel, un compte interne obtiendrait un
    // cookie portail.
    fetchMock
      .mockResolvedValueOnce(AUTH_OK())
      .mockResolvedValueOnce(new Response('', { status: 403 }))
      .mockResolvedValueOnce(json({ result: true }));

    const response = await (await importLogin())(loginRequest(CREDENTIALS));
    expect(response.status).toBe(401);
    expect(jar.raw(PORTAL_COOKIE)).toBeUndefined();

    const destroyed = fetchMock.mock.calls.some(
      ([url]) => String(url).includes('/web/session/destroy'),
    );
    expect(destroyed).toBe(true);
  });

  it('donne le même message pour un identifiant inconnu et un mot de passe faux', async () => {
    // Une fabrique, pas une instance : le corps d'une Response ne se lit qu'une
    // fois, et la réutiliser ferait échouer le second appel pour une tout autre
    // raison que celle qu'on teste.
    fetchMock.mockImplementation(async () => json({ result: { uid: false } }));
    const login = await importLogin();

    const unknown = await (await login(
      loginRequest({ login: 'inconnu@example.com', password: 'x' }),
    )).json();
    resetRateLimits();
    const wrongPassword = await (await login(
      loginRequest({ login: 'client@example.com', password: 'faux' }),
    )).json();

    expect(unknown.error.message).toBe(wrongPassword.error.message);
    expect(unknown.error.code).toBe(wrongPassword.error.code);
  });

  it('refuse une origine tierce avant tout appel à Odoo', async () => {
    const response = await (await importLogin())(
      loginRequest(CREDENTIALS, { origin: 'https://evil.example' }),
    );
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse une requête sans Origin ni Referer', async () => {
    const response = await (await importLogin())(loginRequest(CREDENTIALS, {}));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejette un corps mal formé comme un échec d’identification', async () => {
    const login = await importLogin();
    for (const body of [{}, { login: '', password: '' }, { login: 42, password: 7 }]) {
      resetRateLimits();
      const response = await login(loginRequest(body));
      expect(response.status).toBe(401);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un mot de passe démesuré sans appeler Odoo', async () => {
    const response = await (await importLogin())(
      loginRequest({ login: 'a@b.c', password: 'x'.repeat(5000) }),
    );
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('freine après plusieurs échecs sur le même identifiant', async () => {
    fetchMock.mockImplementation(async () => json({ result: { uid: false } }));
    const login = await importLogin();

    let last = 0;
    for (let attempt = 0; attempt < 8; attempt += 1) {
      last = (await login(loginRequest(CREDENTIALS))).status;
    }
    expect(last).toBe(429);
  });

  it('renvoie 503 quand Odoo est injoignable, jamais 401', async () => {
    // Dire « identifiants invalides » sur une panne ferait douter le client de son
    // mot de passe et déclencherait des réinitialisations inutiles.
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    const response = await (await importLogin())(loginRequest(CREDENTIALS));
    expect(response.status).toBe(503);
  });

  it('marque la réponse no-store', async () => {
    fetchMock.mockResolvedValueOnce(AUTH_OK()).mockResolvedValueOnce(ME_OK());
    const response = await (await importLogin())(loginRequest(CREDENTIALS));
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});

describe('GET /api/portal/me', () => {
  it('renvoie 401 sans cookie, sans appeler Odoo', async () => {
    const response = await (await importMe())();
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renvoie l’identité pour une session valide', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      SECRET,
    ));
    fetchMock.mockResolvedValueOnce(ME_OK());

    const response = await (await importMe())();
    expect(response.status).toBe(200);
    expect((await response.json()).data.name).toBe('Client Test');
  });

  it('renvoie 401 pour un cookie scellé avec un autre secret', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      'z'.repeat(48),
    ));
    const response = await (await importMe())();
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renvoie 401 pour un cookie altéré', async () => {
    const sealed = sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      SECRET,
    );
    const parts = sealed.split('.');
    const data = Buffer.from(parts[2] as string, 'base64url');
    data[0] = (data[0] ?? 0) ^ 0xff;
    parts[2] = data.toString('base64url');
    jar.seed(parts.join('.'));

    expect((await (await importMe())()).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renvoie 401 pour un cookie expiré, sans interroger Odoo', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) - 100_000 },
      SECRET,
    ));
    expect((await (await importMe())()).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renvoie 401 quand Odoo refuse la session', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      SECRET,
    ));
    fetchMock.mockResolvedValueOnce(new Response('', { status: 401 }));
    expect((await (await importMe())()).status).toBe(401);
  });

  it('renvoie 503 — et non 401 — quand Odoo est injoignable', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      SECRET,
    ));
    fetchMock.mockRejectedValueOnce(new Error('down'));
    expect((await (await importMe())()).status).toBe(503);
  });

  it('marque la réponse no-store', async () => {
    const response = await (await importMe())();
    expect(response.headers.get('cache-control')).toContain('no-store');
  });
});

describe('POST /api/portal/auth/logout', () => {
  function logoutRequest(headers: Record<string, string> = { origin: SITE }) {
    return new Request(`${SITE}/api/portal/auth/logout`, { method: 'POST', headers });
  }

  it('détruit la session Odoo puis vide le cookie', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      SECRET,
    ));
    fetchMock.mockResolvedValueOnce(json({ result: true }));

    const response = await (await importLogout())(logoutRequest());
    expect(response.status).toBe(200);
    expect(jar.raw(PORTAL_COOKIE)).toBe('');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/web/session/destroy');
    // La destruction porte bien la session du client : sans le cookie, Odoo
    // détruirait la mauvaise session, ou aucune.
    expect(new Headers(init.headers as HeadersInit).get('cookie'))
      .toBe(`session_id=${ODOO_SESSION}`);
  });

  it('reste idempotent sans session', async () => {
    const response = await (await importLogout())(logoutRequest());
    expect(response.status).toBe(200);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('vide le cookie même quand Odoo est injoignable', async () => {
    jar.seed(sealSession(
      { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) },
      SECRET,
    ));
    fetchMock.mockRejectedValue(new Error('down'));

    const response = await (await importLogout())(logoutRequest());
    expect(response.status).toBe(200);
    expect(jar.raw(PORTAL_COOKIE)).toBe('');
  });

  it('refuse une origine tierce', async () => {
    const response = await (await importLogout())(
      logoutRequest({ origin: 'https://evil.example' }),
    );
    expect(response.status).toBe(403);
  });
});

describe('cloisonnement à travers le BFF', () => {
  it('la session du client A n’obtient jamais la réponse du client B', async () => {
    // Le BFF ne choisit pas quel client il lit : il transmet un cookie et Odoo
    // répond pour CE cookie. Ce test vérifie que rien dans le trajet ne réécrit
    // ni ne mémorise l'identité.
    const me = await importMe();
    const sessionA = 'sessionAAAAAAAAAAAAA';
    const sessionB = 'sessionBBBBBBBBBBBBB';
    const now = Math.floor(Date.now() / 1000);

    jar.seed(sealSession({ odooSessionId: sessionA, issuedAt: now }, SECRET));
    fetchMock.mockResolvedValueOnce(
      json({ success: true, data: { name: 'Client A', email: null, phone: null, company: 'A', city: null, country: null } }),
    );
    expect((await (await me()).json()).data.name).toBe('Client A');

    jar.seed(sealSession({ odooSessionId: sessionB, issuedAt: now }, SECRET));
    fetchMock.mockResolvedValueOnce(
      json({ success: true, data: { name: 'Client B', email: null, phone: null, company: 'B', city: null, country: null } }),
    );
    expect((await (await me()).json()).data.name).toBe('Client B');

    const cookiesSent = fetchMock.mock.calls.map(
      ([, init]) => new Headers((init as RequestInit).headers as HeadersInit).get('cookie'),
    );
    expect(cookiesSent).toEqual([
      `session_id=${sessionA}`,
      `session_id=${sessionB}`,
    ]);
  });

  it('aucun appel portail ne porte de clé d’intégration', async () => {
    process.env.ODOO_API_KEY_SOURCING = 'S'.repeat(32);
    resetServerEnvCache();

    fetchMock.mockResolvedValueOnce(AUTH_OK()).mockResolvedValueOnce(ME_OK());
    await (await importLogin())(loginRequest(CREDENTIALS));

    for (const [, init] of fetchMock.mock.calls as Array<[string, RequestInit]>) {
      const sent = new Headers(init.headers as HeadersInit);
      expect(sent.get('x-api-key')).toBeNull();
      expect(sent.get('authorization')).toBeNull();
      expect(String(init.body ?? '')).not.toContain('S'.repeat(32));
    }
    delete process.env.ODOO_API_KEY_SOURCING;
  });
});

describe('journalisation', () => {
  /**
   * Un grep sur le code prouverait seulement qu'aucun champ sensible n'est passé
   * *aujourd'hui*. Ce test capture ce qui est réellement écrit pendant un cycle
   * complet — connexion, /me, déconnexion — et échouera si un futur ajout de
   * contexte de log fait fuiter une valeur.
   */
  it('n’écrit jamais de valeur sensible, sur aucun chemin', async () => {
    const written: string[] = [];
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((level) =>
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
        written.push(args.map((arg) => JSON.stringify(arg) ?? String(arg)).join(' '));
      }),
    );

    const password = 'MotDePasseDeFixture-93b7f1';

    // 1. connexion réussie
    fetchMock.mockResolvedValueOnce(AUTH_OK()).mockResolvedValueOnce(ME_OK());
    await (await importLogin())(loginRequest({ login: CREDENTIALS.login, password }));
    // 2. /me sous cette session
    fetchMock.mockResolvedValueOnce(ME_OK());
    await (await importMe())();
    // 3. déconnexion
    fetchMock.mockResolvedValueOnce(json({ result: true }));
    await (await importLogout())(
      new Request(`${SITE}/api/portal/auth/logout`, {
        method: 'POST', headers: { origin: SITE },
      }),
    );
    // 4. échec d’identification
    resetRateLimits();
    fetchMock.mockImplementationOnce(async () => json({ result: { uid: false } }));
    await (await importLogin())(loginRequest({ login: CREDENTIALS.login, password }));
    // 5. panne Odoo
    resetRateLimits();
    fetchMock.mockRejectedValueOnce(new Error('down'));
    await (await importLogin())(loginRequest({ login: CREDENTIALS.login, password }));

    spies.forEach((spy) => spy.mockRestore());

    const logs = written.join('\n');
    expect(logs.length).toBeGreaterThan(0); // sinon le test ne prouverait rien

    for (const forbidden of [
      password,
      ODOO_SESSION,
      SECRET,
      'PORTAL_SESSION_SECRET',
      'Cookie:',
      'session_id=',
      'Authorization',
      'x-api-key',
      PORTAL_COOKIE,
    ]) {
      expect(logs).not.toContain(forbidden);
    }
  });
});
