import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { PORTAL_COOKIE, sealSession } from '@/lib/portal/session';

const SITE = 'https://dallytrading.com';
const SECRET = 'd'.repeat(48);
const ODOO_SESSION = 'quotedecisionodoo123456';

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

const QUOTE = {
  reference: 'DT-2026-000777',
  service: 'freight_sea',
  status: 'won',
  createdOn: '2026-08-16',
  origin: 'Dakar, Senegal',
  destination: 'Abidjan, Côte d’Ivoire',
  goodsDescription: 'Marchandise synthétique',
  quantity: '2 conteneurs',
  canDecide: false,
  customerDecisionAt: '2026-08-16 12:00:00',
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
  reference = QUOTE.reference,
) {
  return {
    request: new Request(
      `${SITE}/api/portal/quotes/${reference}/decision`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(body),
      },
    ),
    context: { params: Promise.resolve({ reference }) },
  };
}

async function route() {
  return (await import('./route')).POST;
}

async function call(
  body: unknown,
  headers?: Record<string, string>,
  reference?: string,
) {
  const input = request(body, headers, reference);
  return (await route())(input.request, input.context);
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = SITE;
  process.env.ODOO_URL = 'https://crm.quote-decision.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'integration-key-must-never-be-used';
  process.env.ODOO_API_KEY_SOURCING = 'sourcing-key-must-never-be-used';
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = SECRET;
  // Le site de test est en https, et le schéma exige alors les deux clés
  // boutique : elles sont validées en bloc, y compris pour un test qui n'a
  // rien à voir avec la boutique.
  process.env.ODOO_API_KEY_SHOP_READ = 'shop-read-key-for-tests-only-0123456789';
  process.env.ODOO_API_KEY_SHOP_CHECKOUT = 'shop-checkout-key-for-tests-only-01234';
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

describe('POST /api/portal/quotes/[reference]/decision', () => {
  it.each([
    [{ decision: 'accept' }, 'accept'],
    [{ decision: 'reject', reason: '  Conditions non adaptées  ' }, 'reject'],
  ] as const)('transmet %j sous la session Odoo réelle', async (body, decision) => {
    validSession();
    fetchMock.mockResolvedValueOnce(odoo({
      ...QUOTE,
      status: decision === 'accept' ? 'won' : 'lost',
    }));

    const response = await call(body);
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect((await response.json()).data.status)
      .toBe(decision === 'accept' ? 'won' : 'lost');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      `https://crm.quote-decision.invalid/api/v1/portal/quotes/${QUOTE.reference}/decision`,
    );
    expect(init.method).toBe('POST');
    expect(init.cache).toBe('no-store');
    expect(JSON.parse(String(init.body))).toEqual(
      decision === 'accept'
        ? { decision: 'accept' }
        : { decision: 'reject', reason: 'Conditions non adaptées' },
    );

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
    ['Referer seul', { referer: `${SITE}/espace-client/devis/${QUOTE.reference}` }],
  ])('refuse %s avant toute lecture métier', async (_label, headers) => {
    validSession();
    const response = await call({ decision: 'accept' }, headers);
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse l’absence de cookie sans appeler Odoo', async () => {
    const response = await call({ decision: 'accept' });
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un cookie altéré sans appeler Odoo', async () => {
    validSession();
    const cookie = jar.get(PORTAL_COOKIE)?.value as string;
    const first = cookie[0] === 'A' ? 'B' : 'A';
    jar.seed(`${first}${cookie.slice(1)}`);

    const response = await call({ decision: 'accept' });
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse un cookie local expiré sans appeler Odoo', async () => {
    validSession(Math.floor(Date.now() / 1000) - 100_000);
    const response = await call({ decision: 'accept' });
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ['objet vide', {}],
    ['décision invalide', { decision: 'maybe' }],
    ['motif sur acceptation', { decision: 'accept', reason: 'non' }],
    ['motif trop long', { decision: 'reject', reason: 'x'.repeat(501) }],
    ['motif HTML', { decision: 'reject', reason: '<b>non</b>' }],
    ['state injecté', { decision: 'accept', state: 'won' }],
    ['partner_id injecté', { decision: 'accept', partner_id: 7 }],
    ['mass assignment', {
      decision: 'accept', state: 'won', partner_id: 7, margin: 0, user_id: 1,
    }],
  ])('rejette localement : %s', async (_label, body) => {
    validSession();
    const response = await call(body);
    expect(response.status).toBe(400);
    expect((await response.json()).error.code).toBe('invalid_request');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('borne le corps réel même sans Content-Length', async () => {
    validSession();
    const oversized = new Request(
      `${SITE}/api/portal/quotes/${QUOTE.reference}/decision`,
      {
        method: 'POST',
        headers: { origin: SITE, 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: 'reject', reason: 'é'.repeat(5_000) }),
      },
    );
    expect(oversized.headers.get('content-length')).toBeNull();

    const response = await (await route())(oversized, {
      params: Promise.resolve({ reference: QUOTE.reference }),
    });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refuse une référence malformée comme un 404 sans appel Odoo', async () => {
    validSession();
    const response = await call(
      { decision: 'accept' }, { origin: SITE }, 'invalid reference',
    );
    expect(response.status).toBe(404);
    expect((await response.json()).error.code).toBe('not_found');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    [400, 'invalid_request', 400],
    [403, 'forbidden', 403],
    [404, 'not_found', 404],
    [409, 'conflict', 409],
    [500, 'unavailable', 503],
  ])('traduit Odoo %i/%s en %i', async (odooStatus, code, expected) => {
    validSession();
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ success: false, error: { code } }),
      { status: odooStatus, headers: { 'Content-Type': 'application/json' } },
    ));

    const response = await call({ decision: 'accept' });
    expect(response.status).toBe(expected);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('traite une redirection Odoo comme une session expirée', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(new Response('', {
      status: 303,
      headers: { location: '/web/login' },
    }));
    expect((await call({ decision: 'accept' })).status).toBe(401);
  });

  it('traduit panne et timeout Odoo en 503', async () => {
    validSession();
    fetchMock.mockRejectedValueOnce(new Error('down'));
    expect((await call({ decision: 'accept' })).status).toBe(503);

    const aborted = new Error('aborted');
    aborted.name = 'AbortError';
    fetchMock.mockRejectedValueOnce(aborted);
    expect((await call({ decision: 'accept' })).status).toBe(503);
  });

  it('refuse une projection Odoo inattendue', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(odoo({ ...QUOTE, margin: 9000 }));
    expect((await call({ decision: 'accept' })).status).toBe(503);
  });

  it('ne fait jamais de fallback via une clé d’intégration', async () => {
    validSession();
    fetchMock.mockResolvedValueOnce(new Response('', { status: 403 }));
    await call({ decision: 'accept' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const serialised = JSON.stringify(init);
    expect(serialised).not.toContain(process.env.ODOO_API_KEY);
    expect(serialised).not.toContain(process.env.ODOO_API_KEY_SOURCING);
  });

  it('journalise sans motif, session, cookie ni payload complet', async () => {
    const written: string[] = [];
    for (const level of ['log', 'warn', 'error'] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
        written.push(args.map(String).join(' '));
      });
    }

    validSession();
    fetchMock.mockResolvedValueOnce(odoo({ ...QUOTE, status: 'lost' }));
    const privateReason = 'DALLY_E2E_QUOTE_REJECTION_REASON';
    await call({ decision: 'reject', reason: privateReason });

    const logs = written.join('\n');
    expect(logs).toContain('quote_decision');
    expect(logs).toContain(QUOTE.reference);
    expect(logs).toContain('reject');
    expect(logs).toContain('success');
    for (const forbidden of [
      privateReason,
      ODOO_SESSION,
      SECRET,
      'session_id=',
      'dt_portal_session',
      'Cookie:',
      'Authorization:',
      'margin',
    ]) {
      expect(logs).not.toContain(forbidden);
    }
  });
});
