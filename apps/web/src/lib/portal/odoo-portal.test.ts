import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PortalGatewayError, PortalOdooGateway } from './odoo-portal';
import { resetServerEnvCache } from '@/lib/env';

const CORRELATION = 'test-correlation';
const SESSION = 'sess1234567890abcdef';

function envForTests() {
  process.env.NEXT_PUBLIC_SITE_URL = 'https://dallytrading.com';
  process.env.ODOO_URL = 'https://crm.example.invalid';
  process.env.ODOO_DATABASE = 'test_db';
  process.env.ODOO_API_KEY = 'x'.repeat(32);
  process.env.ODOO_TIMEOUT_MS = '2000';
  process.env.PORTAL_SESSION_SECRET = 's'.repeat(48);
  resetServerEnvCache();
}

/** Réponse Odoo minimale. `setCookie` simule le Set-Cookie de session. */
function odooResponse(
  body: unknown,
  init: { status?: number; setCookie?: string } = {},
): Response {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  if (init.setCookie) headers.append('set-cookie', init.setCookie);
  return new Response(JSON.stringify(body), { status: init.status ?? 200, headers });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  envForTests();
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('authenticate', () => {
  it('renvoie l’identifiant de session émis par Odoo', async () => {
    fetchMock.mockResolvedValue(
      odooResponse(
        { jsonrpc: '2.0', result: { uid: 7 } },
        { setCookie: `session_id=${SESSION}; HttpOnly; Path=/` },
      ),
    );
    const gateway = new PortalOdooGateway();
    await expect(gateway.authenticate('client@example.com', 'pw', CORRELATION))
      .resolves.toBe(SESSION);
  });

  it('n’envoie jamais de clé d’API', async () => {
    fetchMock.mockResolvedValue(
      odooResponse({ result: { uid: 7 } }, { setCookie: `session_id=${SESSION}` }),
    );
    await new PortalOdooGateway().authenticate('a@b.c', 'pw', CORRELATION);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const sent = new Headers(init.headers as HeadersInit);
    expect(sent.get('x-api-key')).toBeNull();
    expect(sent.get('authorization')).toBeNull();
    expect(JSON.stringify(init.headers)).not.toContain('api');
  });

  it('renvoie invalid_credentials sur un uid absent', async () => {
    fetchMock.mockResolvedValue(odooResponse({ result: { uid: false } }));
    await expect(
      new PortalOdooGateway().authenticate('a@b.c', 'faux', CORRELATION),
    ).rejects.toMatchObject({ code: 'invalid_credentials' });
  });

  it('renvoie invalid_credentials sur une erreur JSON-RPC', async () => {
    // Odoo répond 200 avec un objet `error` : traiter cela comme un succès
    // établirait une session inexistante.
    fetchMock.mockResolvedValue(odooResponse({ error: { message: 'Access denied' } }));
    await expect(
      new PortalOdooGateway().authenticate('a@b.c', 'pw', CORRELATION),
    ).rejects.toMatchObject({ code: 'invalid_credentials' });
  });

  it('échoue si Odoo authentifie sans émettre de cookie', async () => {
    fetchMock.mockResolvedValue(odooResponse({ result: { uid: 7 } }));
    await expect(
      new PortalOdooGateway().authenticate('a@b.c', 'pw', CORRELATION),
    ).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('normalise une panne réseau en unavailable', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    await expect(
      new PortalOdooGateway().authenticate('a@b.c', 'pw', CORRELATION),
    ).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('normalise une coupure de délai en timeout', async () => {
    const aborted = new Error('aborted');
    aborted.name = 'AbortError';
    fetchMock.mockRejectedValue(aborted);
    await expect(
      new PortalOdooGateway().authenticate('a@b.c', 'pw', CORRELATION),
    ).rejects.toMatchObject({ code: 'timeout' });
  });
});

describe('get', () => {
  function ok(data: unknown) {
    return odooResponse({ success: true, data });
  }

  it('transporte la session dans l’en-tête Cookie', async () => {
    fetchMock.mockResolvedValue(ok({ name: 'Client' }));
    await new PortalOdooGateway().get('/me', SESSION, CORRELATION);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://crm.example.invalid/api/v1/portal/me');
    expect(new Headers(init.headers as HeadersInit).get('cookie'))
      .toBe(`session_id=${SESSION}`);
  });

  it('refuse un identifiant de session malformé sans appeler Odoo', async () => {
    // Garde anti-injection d’en-tête : un retour chariot ouvrirait une seconde ligne.
    await expect(
      new PortalOdooGateway().get('/me', 'abc\r\nX-Evil: 1', CORRELATION),
    ).rejects.toMatchObject({ code: 'unauthenticated' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('n’active jamais le cache', async () => {
    fetchMock.mockResolvedValue(ok({}));
    await new PortalOdooGateway().get('/me', SESSION, CORRELATION);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.cache).toBe('no-store');
  });

  it.each([401, 403])('traduit %i en unauthenticated', async (status) => {
    fetchMock.mockResolvedValue(new Response('', { status }));
    await expect(
      new PortalOdooGateway().get('/me', SESSION, CORRELATION),
    ).rejects.toMatchObject({ code: 'unauthenticated' });
  });

  it('traite une redirection comme une session expirée', async () => {
    // Odoo renvoie 303 vers /web/login quand la session est morte. Suivre la
    // redirection donnerait une page HTML de connexion avec un statut 200.
    fetchMock.mockResolvedValue(
      new Response('', { status: 303, headers: { location: '/web/login' } }),
    );
    await expect(
      new PortalOdooGateway().get('/me', SESSION, CORRELATION),
    ).rejects.toMatchObject({ code: 'unauthenticated' });
  });

  it('ne suit pas les redirections', async () => {
    fetchMock.mockResolvedValue(ok({}));
    await new PortalOdooGateway().get('/me', SESSION, CORRELATION);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.redirect).toBe('manual');
  });

  it('traduit 404 en not_found', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 404 }));
    await expect(
      new PortalOdooGateway().get('/documents/1', SESSION, CORRELATION),
    ).rejects.toMatchObject({ code: 'not_found' });
  });

  it('refuse une enveloppe sans success', async () => {
    fetchMock.mockResolvedValue(odooResponse({ data: { name: 'X' } }));
    await expect(
      new PortalOdooGateway().get('/me', SESSION, CORRELATION),
    ).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('refuse une réponse non JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<html>502</html>', { status: 200 }));
    await expect(
      new PortalOdooGateway().get('/me', SESSION, CORRELATION),
    ).rejects.toMatchObject({ code: 'unavailable' });
  });

  it('ne rejoue jamais avec une clé d’intégration après un refus', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 403 }));
    await expect(
      new PortalOdooGateway().get('/me', SESSION, CORRELATION),
    ).rejects.toBeInstanceOf(PortalGatewayError);
    // Un seul appel : pas de seconde tentative, donc pas de repli possible.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('destroySession', () => {
  it('avale les erreurs — une déconnexion ne doit pas échouer', async () => {
    fetchMock.mockRejectedValue(new Error('down'));
    await expect(
      new PortalOdooGateway().destroySession(SESSION, CORRELATION),
    ).resolves.toBeUndefined();
  });

  it('avale aussi un identifiant malformé', async () => {
    await expect(
      new PortalOdooGateway().destroySession('court', CORRELATION),
    ).resolves.toBeUndefined();
  });
});
