import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Les deux routes du chargement, vues du BFF.
 *
 * Ce qui leur est propre : leur budget de débit, distinct de celui des
 * réceptions, le refus d'une référence de départ mal formée **avant** tout
 * réseau, et l'absence totale de verbe d'écriture autre que le POST.
 */

vi.mock('@/lib/auth/auth', () => ({ readOpsSession: vi.fn() }));
vi.mock('@/lib/ops/loading', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/ops/loading')>();
  return {
    ...original,
    fetchLoadings: vi.fn(), fetchLoading: vi.fn(), applyLoading: vi.fn(),
  };
});

const { readOpsSession } = await import('@/lib/auth/auth');
const { applyLoading, fetchLoading, fetchLoadings } = await import('@/lib/ops/loading');
const { OpsGatewayError } = await import('@/lib/auth/odoo-ops');
const { resetRateLimits } = await import('@/lib/rate-limit');

const liste = await import('@/app/api/consolidations/loading/route');
const detail = await import('@/app/api/consolidations/[reference]/loading/route');

const REFERENCE = 'AIR-DSS-CDG-2026-002';
const LIEU = { country_code: 'SN', city: 'Dakar', location: 'DSS' };

const RESUME = {
  shipments_expected: 1, shipments_complete: 0,
  packages_expected: 2, packages_loaded: 1, packages_partial: 0,
  packages_remaining: 1, packages_blocked: 0,
  quantity_expected: 2, quantity_loaded: 1,
  weight_expected_kg: 10, weight_loaded_kg: 5,
  volume_expected_cbm: 0.1, volume_loaded_cbm: 0.05,
};

const ENTETE = {
  reference: REFERENCE, state: 'collecting', state_label: 'Collecte ouverte',
  transport_mode: 'air', direction: 'export',
  origin: LIEU, destination: { ...LIEU, city: 'Paris', location: 'CDG' },
  collection_close_on: '', scheduled_departure: '', can_load: true,
};

const DETAIL = { ...ENTETE, summary: RESUME, shipments: [] };

function lister(requete = ''): Promise<Response> {
  return liste.GET(
    new Request(`https://ops.test/api/consolidations/loading${requete}`),
  ) as unknown as Promise<Response>;
}

function consulter(reference = REFERENCE): Promise<Response> {
  return detail.GET(
    new Request(
      `https://ops.test/api/consolidations/${encodeURIComponent(reference)}/loading`),
    { params: Promise.resolve({ reference }) },
  ) as unknown as Promise<Response>;
}

function appliquer(reference = REFERENCE, corps: unknown = {
  request_uuid: '11111111-2222-4333-8444-555555555555',
  action: 'load', package_reference: 'colis-1',
}): Promise<Response> {
  return detail.POST(
    new Request(
      `https://ops.test/api/consolidations/${encodeURIComponent(reference)}/loading`,
      {
        method: 'POST', body: JSON.stringify(corps),
        // Sans en-tête `Origin` : un client non-navigateur légitime n'en
        // envoie pas, et `origineAcceptable` ne refuse qu'une origine
        // présente et différente.
        headers: { 'Content-Type': 'application/json' },
      }),
    { params: Promise.resolve({ reference }) },
  ) as unknown as Promise<Response>;
}

beforeEach(() => {
  resetRateLimits();
  vi.mocked(readOpsSession).mockReset();
  vi.mocked(fetchLoadings).mockReset();
  vi.mocked(fetchLoading).mockReset();
  vi.mocked(applyLoading).mockReset();
  vi.mocked(readOpsSession).mockResolvedValue({ odooSessionId: 'session', issuedAt: 1 });
  vi.mocked(fetchLoadings).mockResolvedValue({ consolidations: [{ ...ENTETE, summary: RESUME }] });
  vi.mocked(fetchLoading).mockResolvedValue({ loading: DETAIL });
  vi.mocked(applyLoading).mockResolvedValue({ replayed: false, loading: DETAIL });
});

describe('la liste des départs', () => {
  it('sert le contrat, sans cache', async () => {
    const reponse = await lister();
    expect(reponse.status).toBe(200);
    expect(await reponse.json()).toEqual({
      success: true, data: { consolidations: [{ ...ENTETE, summary: RESUME }] },
    });
    expect(reponse.headers.get('Cache-Control'))
      .toBe('private, no-store, max-age=0');
  });

  it('refuse tout filtre : la portée est décidée par le serveur', async () => {
    const reponse = await lister('?company=2');
    expect(reponse.status).toBe(400);
    expect(fetchLoadings).not.toHaveBeenCalled();
  });

  it('refuse l’absence de session avant d’interroger Odoo', async () => {
    vi.mocked(readOpsSession).mockResolvedValue(null);
    expect((await lister()).status).toBe(401);
    expect(fetchLoadings).not.toHaveBeenCalled();
  });

  it('un refus d’Odoo devient une session expirée, jamais un 403 nu', async () => {
    vi.mocked(fetchLoadings).mockRejectedValue(new OpsGatewayError('forbidden'));
    expect((await lister()).status).toBe(401);
  });

  it('une panne reste une panne, sans détail technique', async () => {
    vi.mocked(fetchLoadings).mockRejectedValue(new Error('pg down'));
    const reponse = await lister();
    expect(reponse.status).toBe(503);
    expect(JSON.stringify(await reponse.json())).not.toContain('pg down');
  });
});

describe('le détail d’un départ', () => {
  it('sert le contrat', async () => {
    const reponse = await consulter();
    expect(reponse.status).toBe(200);
    expect(await reponse.json()).toEqual({
      success: true, data: { loading: DETAIL },
    });
  });

  it('refuse une référence mal formée sans jamais toucher au réseau', async () => {
    for (const mauvaise of ['../identity', 'A B', ' AIR', 'A/B', '']) {
      const reponse = await consulter(mauvaise);
      expect(reponse.status, mauvaise).toBe(400);
    }
    expect(fetchLoading).not.toHaveBeenCalled();
    expect(readOpsSession).not.toHaveBeenCalled();
  });

  it('ne redécode jamais le segment : App Router l’a déjà fait', async () => {
    await consulter(REFERENCE);
    expect(vi.mocked(fetchLoading).mock.calls[0]?.[0]).toBe(REFERENCE);
  });

  it('un départ inconnu vaut 404', async () => {
    vi.mocked(fetchLoading).mockRejectedValue(new OpsGatewayError('not_found'));
    expect((await consulter()).status).toBe(404);
  });
});

describe('le geste', () => {
  it('passe la référence validée, et le corps tel quel', async () => {
    const reponse = await appliquer();
    expect(reponse.status).toBe(200);
    expect(vi.mocked(applyLoading).mock.calls[0]?.[0]).toBe(REFERENCE);
    expect(vi.mocked(applyLoading).mock.calls[0]?.[1]).toEqual({
      request_uuid: '11111111-2222-4333-8444-555555555555',
      action: 'load', package_reference: 'colis-1',
    });
  });

  it('refuse une référence mal formée avant tout contrôle de session', async () => {
    const reponse = await appliquer('../identity');
    expect(reponse.status).toBe(400);
    expect(applyLoading).not.toHaveBeenCalled();
  });

  it('refuse un corps qui porte une quantité', async () => {
    const reponse = await appliquer(REFERENCE, {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      action: 'load', package_reference: 'colis-1', quantity: 1,
    });
    expect(reponse.status).toBe(400);
    expect(applyLoading).not.toHaveBeenCalled();
  });

  it('refuse une action que le contrat ne nomme pas', async () => {
    const reponse = await appliquer(REFERENCE, {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      action: 'depart', package_reference: 'colis-1',
    });
    expect(reponse.status).toBe(400);
    expect(applyLoading).not.toHaveBeenCalled();
  });
});

describe('aucun autre verbe n’existe', () => {
  it('les modules n’exportent que ce qui est servi', () => {
    expect(Object.keys(liste).sort()).toEqual(['GET', 'dynamic']);
    expect(Object.keys(detail).sort()).toEqual(['GET', 'POST', 'dynamic']);
  });
});

describe('le budget est le sien', () => {
  it('le chargement ne consomme pas le débit d’une réception', async () => {
    const routeSource = await import('node:fs').then(({ readFileSync }) =>
      readFileSync(new URL(
        './[reference]/loading/route.ts', import.meta.url), 'utf8'));
    expect(routeSource).toContain('OPS_LOADING_SESSION');
    expect(routeSource).toContain('cleChargementDemande');
    expect(routeSource).not.toContain('OPS_INTAKE');
  });
});
