import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { IntakeSearchPage } from '@/lib/ops/intake-search';

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/ops/intake-search', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/intake-search')>();
  return { ...original, searchIntakes: vi.fn() };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { searchIntakes } = await import('@/lib/ops/intake-search');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { clearRateLimitKey, cleRechercheSession, cleRechercheIp } =
  await import('@/lib/rate-limit');
const { GET } = await import('@/app/api/intakes/search/route');

const VIDE: IntakeSearchPage = { items: [], has_more: false };

function appel(url: string): Promise<Response> {
  return GET(new Request(url)) as unknown as Promise<Response>;
}

beforeEach(() => {
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(searchIntakes).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(searchIntakes).mockResolvedValue(VIDE);
  clearRateLimitKey(cleRechercheSession('session'));
  clearRateLimitKey(cleRechercheIp('inconnue'));
});

describe('BFF recherche de dossier', () => {
  it('relaie la requête et interdit la mise en cache', async () => {
    const reponse = await appel('https://ops.test/api/intakes/search?q=A012');
    expect(reponse.status).toBe(200);
    expect(reponse.headers.get('cache-control')).toContain('no-store');
    expect(searchIntakes).toHaveBeenCalledWith(
      { q: 'A012' }, 'session', expect.any(String));
  });

  it('refuse l’absence de session avant d’interroger Odoo', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    const reponse = await appel('https://ops.test/api/intakes/search?q=A012');
    expect(reponse.status).toBe(401);
    expect(searchIntakes).not.toHaveBeenCalled();
  });

  it('refuse une requête vide, un filtre inconnu, un plafond démesuré', async () => {
    for (const url of [
      'https://ops.test/api/intakes/search',
      'https://ops.test/api/intakes/search?q=',
      'https://ops.test/api/intakes/search?q=%20%20',
      'https://ops.test/api/intakes/search?q=A012&sudo=1',
      // Un curseur n'est plus un paramètre : le refuser empêche de
      // redemander une clé de parcours par la porte du BFF.
      'https://ops.test/api/intakes/search?q=A012&cursor=MTMxNA%3D%3D',
      'https://ops.test/api/intakes/search?q=A012&limit=5000',
      'https://ops.test/api/intakes/search?q=A012&limit=0',
      `https://ops.test/api/intakes/search?q=${'a'.repeat(200)}`,
    ]) {
      expect((await appel(url)).status, url).toBe(400);
    }
    expect(searchIntakes).not.toHaveBeenCalled();
  });

  it('traduit le refus d’Odoo sans réécrire sa règle', async () => {
    vi.mocked(searchIntakes).mockRejectedValue(
      new OpsGatewayError('invalid_request', 'trop court'));
    const reponse = await appel('https://ops.test/api/intakes/search?q=ab');
    expect(reponse.status).toBe(400);
    expect((await reponse.json()).error).toBe('Précisez votre recherche.');
  });

  it('traduit une session périmée côté Odoo en 401', async () => {
    vi.mocked(searchIntakes).mockRejectedValue(
      new OpsGatewayError('forbidden', 'refus'));
    expect((await appel('https://ops.test/api/intakes/search?q=A012')).status).toBe(401);
  });

  it('ne laisse jamais fuir le détail d’une panne', async () => {
    vi.mocked(searchIntakes).mockRejectedValue(new Error('ECONNREFUSED 127.0.0.1:18169'));
    const reponse = await appel('https://ops.test/api/intakes/search?q=A012');
    expect(reponse.status).toBe(503);
    const corps = JSON.stringify(await reponse.json());
    expect(corps).not.toContain('ECONNREFUSED');
    expect(corps).not.toContain('18169');
  });

  it('finit par refuser quand la session cherche sans relâche', async () => {
    let dernier = 200;
    for (let essai = 0; essai < 120 && dernier !== 429; essai += 1) {
      dernier = (await appel('https://ops.test/api/intakes/search?q=A012')).status;
    }
    expect(dernier).toBe(429);
  });

  it('n’expose aucun verbe d’écriture', async () => {
    const routeModule = await import('@/app/api/intakes/search/route');
    expect(Object.keys(routeModule).filter((cle) => cle !== 'GET' && cle !== 'dynamic'))
      .toEqual([]);
  });
});
