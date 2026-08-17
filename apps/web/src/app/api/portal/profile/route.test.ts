import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { PORTAL_COOKIE, sealSession } from '@/lib/portal/session';

const SITE = 'https://dallytrading.com';
const SECRET = 'q'.repeat(48);
const ODOO_SESSION = 'profileodoo123456789';

class CookieJar {
  private readonly store = new Map<string, string>();

  get(name: string) {
    const value = this.store.get(name);
    return value === undefined ? undefined : { name, value };
  }

  set(name: string, value: string) {
    this.store.set(name, value);
  }

  seed(value: string) {
    this.store.set(PORTAL_COOKIE, value);
  }
}

let jar: CookieJar;
let fetchMock: ReturnType<typeof vi.fn>;

vi.mock('next/headers', () => ({ cookies: async () => jar }));

const PROFILE = {
  name: 'Client Profil',
  email: 'client@profile.invalid',
  phone: '+221 77 000 00 00',
  company: 'Profil SARL',
  street: '1 rue de Test',
  street2: null,
  zip: '11000',
  city: 'Dakar',
  country: 'Sénégal',
};

function odoo(data: unknown, status = 200) {
  return new Response(JSON.stringify({ success: status < 400, data }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function validSession(issuedAt = Math.floor(Date.now() / 1000)) {
  jar.seed(sealSession({ odooSessionId: ODOO_SESSION, issuedAt }, SECRET));
}

function request(
  body: unknown,
  headers: Record<string, string> = { origin: SITE },
) {
  return new Request(`${SITE}/api/portal/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

async function route() {
  return (await import('./route')).PATCH;
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ODOO_URL = 'https://crm.profile.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'integration-key-must-never-be-used';
  process.env.ODOO_API_KEY_SOURCING = 'sourcing-key-must-never-be-used';
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = SECRET;
  process.env.SHOP_CART_SECRET = 'shop-cart-secret-for-tests-'.padEnd(48, 'x');
  resetServerEnvCache();

  jar = new CookieJar();
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('PATCH /api/portal/profile', () => {
  it('transmet uniquement le diff validé sous la session Odoo réelle', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(odoo({
      ...PROFILE,
      phone: '+221 77 222 33 44',
      city: 'Dakar Plateau',
    }));

    const response = await (await route())(request({
      phone: '  +221 77 222 33 44  ',
      city: '  Dakar Plateau  ',
    }));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect((await response.json()).data.city).toBe('Dakar Plateau');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crm.profile.invalid/api/v1/portal/profile');
    expect(init.method).toBe('PATCH');
    expect(init.cache).toBe('no-store');
    expect(JSON.parse(String(init.body))).toEqual({
      phone: '+221 77 222 33 44',
      city: 'Dakar Plateau',
    });

    const sent = new Headers(init.headers as HeadersInit);
    expect(sent.get('cookie')).toBe(`session_id=${ODOO_SESSION}`);
    expect(sent.get('x-request-id')).toMatch(/^[A-Za-z0-9_.-]+$/);
    expect(sent.get('x-api-key')).toBeNull();
    expect(sent.get('authorization')).toBeNull();
  });

  it.each([
    ['origine externe', { origin: 'https://evil.example' }],
    ['même hôte en HTTP', { origin: 'http://dallytrading.com' }],
    ['Origin absent', {}],
    ['Referer seul', { referer: `${SITE}/espace-client/profil` }],
  ])('refuse %s avant toute lecture métier', async (_label, headers) => {
    validSession();
    const response = await (await route())(request({ phone: '+221 77 1' }, headers));
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse l’absence de cookie sans appeler Odoo', async () => {
    const response = await (await route())(request({ phone: '+221 77 1' }));
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un cookie altéré sans appeler Odoo', async () => {
    validSession();
    const cookie = jar.get(PORTAL_COOKIE)?.value as string;

    // Altérer le DERNIER caractère ne suffit pas, et ce test l'a prouvé en
    // échouant environ une fois sur quatre. Le tag GCM fait 16 octets, soit 22
    // caractères base64url dont le dernier ne porte que 2 bits utiles : une
    // substitution sur quatre redonne exactement les mêmes octets. Le tag
    // restait valide, la session s'ouvrait, et la requête poursuivait — d'où un
    // 503 au lieu du 401 attendu, de façon intermittente.
    //
    // On altère donc le PREMIER caractère du tag, dont les six bits sont tous
    // significatifs, en imposant une valeur différente de l'actuelle.
    const parts = cookie.split('.');
    const tag = parts[3] as string;
    parts[3] = (tag[0] === 'A' ? 'B' : 'A') + tag.slice(1);
    jar.seed(parts.join('.'));

    const response = await (await route())(request({ phone: '+221 77 1' }));
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un cookie local expiré sans appeler Odoo', async () => {
    validSession(Math.floor(Date.now() / 1000) - 100_000);
    const response = await (await route())(request({ phone: '+221 77 1' }));
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ['objet vide', {}],
    ['partner_id injecté', { partner_id: 7 }],
    ['mass assignment', { phone: '+221 77 1', company_id: 1, groups_id: [4] }],
    ['nom vide', { name: '   ' }],
    ['ville trop longue', { city: 'x'.repeat(129) }],
    ['téléphone invalide', { phone: 'javascript:alert(1)' }],
    ['HTML', { street: '<b>Rue</b>' }],
  ])('rejette localement : %s', async (_label, body) => {
    validSession();
    const response = await (await route())(request(body));
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe('invalid_request');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('borne le corps réel même sans Content-Length', async () => {
    validSession();
    const oversized = new Request(`${SITE}/api/portal/profile`, {
      method: 'PATCH',
      headers: { origin: SITE, 'Content-Type': 'application/json' },
      body: JSON.stringify({ city: 'é'.repeat(9_000) }),
    });
    expect(oversized.headers.get('content-length')).toBeNull();

    const response = await (await route())(oversized);
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un JSON malformé sans appeler Odoo', async () => {
    validSession();
    const malformed = new Request(`${SITE}/api/portal/profile`, {
      method: 'PATCH',
      headers: { origin: SITE, 'Content-Type': 'application/json' },
      body: '{"phone":',
    });
    const response = await (await route())(malformed);
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [400, 'invalid_request', 400],
    [403, 'forbidden', 403],
    [500, 'unavailable', 503],
  ])('traduit Odoo %i/%s en %i', async (odooStatus, code, expected) => {
    validSession();
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ success: false, error: { code } }),
      { status: odooStatus, headers: { 'Content-Type': 'application/json' } },
    ));

    const response = await (await route())(request({ phone: '+221 77 1' }));
    expect(response.status).toBe(expected);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('traite une redirection Odoo comme une session expirée', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(new Response('', {
      status: 303,
      headers: { location: '/web/login' },
    }));
    const response = await (await route())(request({ phone: '+221 77 1' }));
    expect(response.status).toBe(401);
  });

  it('traduit panne et timeout Odoo en 503', async () => {
    validSession();
    fetchMock.mockRejectedValueOnce(new Error('down'));
    expect((await (await route())(request({ phone: '+221 77 1' }))).status).toBe(503);

    const aborted = new Error('aborted');
    aborted.name = 'AbortError';
    fetchMock.mockRejectedValueOnce(aborted);
    expect((await (await route())(request({ phone: '+221 77 1' }))).status).toBe(503);
  });

  it('refuse une projection Odoo inattendue', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(odoo({ ...PROFILE, margin: 9000 }));
    const response = await (await route())(request({ phone: '+221 77 1' }));
    expect(response.status).toBe(503);
  });

  it('ne fait jamais de fallback via une clé d’intégration', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(new Response('', { status: 403 }));
    await (await route())(request({ phone: '+221 77 1' }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const serialised = JSON.stringify(init);
    expect(serialised).not.toContain(process.env.ODOO_API_KEY);
    expect(serialised).not.toContain(process.env.ODOO_API_KEY_SOURCING);
  });

  it('journalise le résultat sans session, secret ni données personnelles', async () => {
    const written: string[] = [];
    for (const level of ['log', 'warn', 'error'] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
        written.push(args.map(String).join(' '));
      });
    }

    validSession();
    fetchMock.mockResolvedValueOnce(odoo({
      ...PROFILE,
      phone: '+221 77 909 90 90',
      street: '99 avenue privée',
    }));
    await (await route())(request({
      phone: '+221 77 909 90 90',
      street: '99 avenue privée',
    }));

    const logs = written.join('\n');
    expect(logs).toContain('profile_update');
    expect(logs).toContain('success');
    for (const forbidden of [
      ODOO_SESSION,
      SECRET,
      '+221 77 909 90 90',
      '99 avenue privée',
      'session_id=',
      'dt_portal_session',
      'Cookie:',
      'Authorization:',
    ]) {
      expect(logs).not.toContain(forbidden);
    }
  });
});
