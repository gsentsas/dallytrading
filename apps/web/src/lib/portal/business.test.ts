/**
 * La DAL métier : ce qu'elle envoie, ce qu'elle accepte, ce qu'elle refuse.
 *
 * `fetch` et le magasin de cookies sont simulés ; tout le reste — scellement,
 * passerelle, schémas — est le code de production. Simuler la passerelle rendrait
 * ces tests verts sans rien prouver de la chaîne.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetServerEnvCache } from '@/lib/env';
import { PORTAL_COOKIE, sealSession } from './session';

const SECRET = 'b'.repeat(48);
const ODOO_SESSION = 'businesssession12345';

class CookieJar {
  private readonly store = new Map<string, string>();
  get(name: string) {
    const value = this.store.get(name);
    return value === undefined ? undefined : { name, value };
  }
  set(name: string, value: string) { this.store.set(name, value); }
  seed(value: string) { this.store.set(PORTAL_COOKIE, value); }
  clear() { this.store.clear(); }
}

let jar: CookieJar;
let fetchMock: ReturnType<typeof vi.fn>;

vi.mock('next/headers', () => ({ cookies: async () => jar }));

function ok(data: unknown) {
  return new Response(JSON.stringify({ success: true, data }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = 'http://127.0.0.1:3020';
  process.env.ODOO_URL = 'http://odoo.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'k'.repeat(32);
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
  jar.seed(sealSession(
    { odooSessionId: ODOO_SESSION, issuedAt: Math.floor(Date.now() / 1000) }, SECRET,
  ));
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => { vi.unstubAllGlobals(); });

async function dal() {
  return import('./business');
}

const QUOTE = {
  reference: 'DT-1', service: null, status: 'new', createdOn: null,
  origin: null, destination: null, goodsDescription: null, quantity: null,
  canDecide: false, customerDecisionAt: null,
};

describe('transport', () => {
  it('porte la session du client et jamais de clé d’API', async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [QUOTE], total: 1, limit: 20, offset: 0 }));
    await (await dal()).listQuotes(1, 'corr');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers as HeadersInit);
    expect(headers.get('cookie')).toBe(`session_id=${ODOO_SESSION}`);
    expect(headers.get('x-api-key')).toBeNull();
    expect(headers.get('authorization')).toBeNull();
    expect(url).toContain('/api/v1/portal/quotes');
    expect(init.cache).toBe('no-store');
  });

  it('refuse d’appeler Odoo sans session', async () => {
    jar.clear();
    await expect((await dal()).listQuotes(1, 'corr'))
      .rejects.toMatchObject({ code: 'unauthenticated' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('encode la référence dans l’URL', async () => {
    fetchMock.mockResolvedValueOnce(ok(QUOTE));
    await (await dal()).getQuote('DT/2026 000001', 'corr');
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain('DT%2F2026%20000001');
    expect(url).not.toContain('DT/2026 000001');
  });
});

describe('pagination', () => {
  it('calcule le décalage à partir de la page', async () => {
    const { offsetForPage, PAGE_SIZE } = await dal();
    expect(offsetForPage(1)).toBe(0);
    expect(offsetForPage(3)).toBe(2 * PAGE_SIZE);
  });

  it('ramène une page absurde à la première', async () => {
    const { offsetForPage } = await dal();
    for (const page of [0, -5, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(offsetForPage(page)).toBe(0);
    }
  });

  it('borne un décalage démesuré plutôt que de le transmettre', async () => {
    const { offsetForPage, PAGE_SIZE } = await dal();
    expect(offsetForPage(1e9)).toBe(10_000 * PAGE_SIZE);
  });

  it('demande toujours une limite bornée', async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0, limit: 20, offset: 0 }));
    const { listShipments, PAGE_SIZE } = await dal();
    await listShipments(2, 'corr');
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain(`limit=${PAGE_SIZE}`);
    expect(url).toContain(`offset=${PAGE_SIZE}`);
  });
});

describe('erreurs normalisées', () => {
  it.each([
    [404, 'not_found'],
    [401, 'unauthenticated'],
    [403, 'unauthenticated'],
  ])('traduit %i en %s', async (status, code) => {
    fetchMock.mockResolvedValueOnce(new Response('', { status }));
    await expect((await dal()).getQuote('DT-1', 'corr')).rejects.toMatchObject({ code });
  });

  it('traduit une panne réseau en unavailable', async () => {
    fetchMock.mockRejectedValueOnce(new Error('down'));
    await expect((await dal()).getQuote('DT-1', 'corr'))
      .rejects.toMatchObject({ code: 'unavailable' });
  });

  it('refuse un payload qui ne correspond pas au contrat', async () => {
    // Odoo renverrait `margin` : la page doit échouer, pas afficher.
    fetchMock.mockResolvedValueOnce(ok({ ...QUOTE, margin: 4200 }));
    await expect((await dal()).getQuote('DT-1', 'corr'))
      .rejects.toMatchObject({ code: 'unavailable' });
  });

  it('ne fait jamais de seconde tentative après un refus', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 403 }));
    await expect((await dal()).getQuote('DT-1', 'corr')).rejects.toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('listes vides', () => {
  it('accepte une liste vide sans erreur', async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0, limit: 20, offset: 0 }));
    const list = await (await dal()).listDocuments(1, 'corr');
    expect(list.items).toHaveLength(0);
    expect(list.total).toBe(0);
  });
});

describe('documents', () => {
  it('extrait l’identifiant de la référence publique', async () => {
    const { documentIdFromReference } = await dal();
    expect(documentIdFromReference('DOC-42')).toBe(42);
  });

  it.each(['DOC-', 'DOC-abc', '42', 'DOC-0', 'DOC--1', '../../etc/passwd',
           'DOC-1;DROP', 'DOC-99999999999999999999'])(
    'refuse la référence forgée %s', async (reference) => {
      const { documentIdFromReference } = await dal();
      expect(documentIdFromReference(reference)).toBeNull();
    });

  it('n’appelle pas Odoo pour une référence malformée', async () => {
    await expect((await dal()).downloadDocument('DOC-abc', 'corr'))
      .rejects.toMatchObject({ code: 'not_found' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rapporte les octets et un nom de fichier assaini', async () => {
    fetchMock.mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3]), {
      status: 200,
      headers: {
        'Content-Disposition': 'attachment; filename="fac ture.pdf"',
        'Content-Type': 'application/octet-stream',
      },
    }));
    const result = await (await dal()).downloadDocument('DOC-7', 'corr');
    expect(new Uint8Array(result.body)).toEqual(new Uint8Array([1, 2, 3]));
    expect(result.filename).toBe('fac ture.pdf');
  });

  it('assainit un nom de fichier hostile', async () => {
    const { safeFilename } = await import('./odoo-portal');
    // Un nom contenant un guillemet ou un saut de ligne permettrait d'injecter
    // un en-tête supplémentaire dans notre réponse.
    expect(safeFilename('attachment; filename="a\\"; X-Evil: 1"')).not.toContain('"');
    expect(safeFilename('attachment; filename="a\r\nX: 1"')).not.toContain('\n');
    expect(safeFilename(null)).toBe('document');
    expect(safeFilename('attachment; filename=""')).toBe('document');
  });

  it('traduit un document d’un autre client en not_found', async () => {
    fetchMock.mockResolvedValueOnce(new Response('', { status: 404 }));
    await expect((await dal()).downloadDocument('DOC-3', 'corr'))
      .rejects.toMatchObject({ code: 'not_found' });
  });
});

describe('aucune identité fournie par l’appelant', () => {
  it('aucune URL de la DAL ne transporte de partner_id', async () => {
    const responses: Record<string, unknown> = {
      quotes: { items: [], total: 0, limit: 20, offset: 0 },
    };
    fetchMock.mockImplementation(async () => ok(responses.quotes));
    const api = await dal();
    await api.listQuotes(1, 'corr');
    await api.listSourcing(1, 'corr');
    await api.listTrades(1, 'corr');
    await api.listShipments(1, 'corr');
    await api.listDocuments(1, 'corr');

    for (const [url, init] of fetchMock.mock.calls as Array<[string, RequestInit]>) {
      expect(url).not.toMatch(/partner_id|customer_id|user_id|domain/i);
      expect(init.body ?? '').toBe('');
    }
  });
});
