import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', () => ({ opsGet: vi.fn(), opsPost: vi.fn() }));

const { opsGet, opsPost } = await import('@/lib/auth/odoo-ops');
const {
  applyLoading, chargementApplique, demandeChargement, detailChargement,
  fetchLoading, fetchLoadings, listeChargement, normaliserReferenceDepart,
} = await import('@/lib/ops/loading');

const LIEU = { country_code: 'SN', city: 'Dakar', location: 'DSS' };
const ARRIVEE = { country_code: 'FR', city: 'Paris', location: 'CDG' };

const RESUME = {
  shipments_expected: 2, shipments_complete: 1,
  packages_expected: 3, packages_loaded: 2, packages_partial: 0,
  packages_remaining: 1, packages_blocked: 0,
  quantity_expected: 5, quantity_loaded: 3,
  weight_expected_kg: 40.5, weight_loaded_kg: 27,
  volume_expected_cbm: 0.12, volume_loaded_cbm: 0.08,
};

const ENTETE = {
  reference: 'AIR-DSS-CDG-2026-002',
  state: 'collecting', state_label: 'Collecte ouverte',
  transport_mode: 'air', direction: 'export',
  origin: LIEU, destination: ARRIVEE,
  collection_close_on: '2026-09-05', scheduled_departure: '2026-09-08',
  can_load: true,
};

const COLIS = {
  reference: 'd6f1b0c2-1111-4222-8333-444455556666',
  description: 'Savon', goods_category: 'Non alimentaire',
  package_type: 'parcel',
  expected_quantity: 2, loaded_quantity: 2, remaining_quantity: 0,
  exact_weight_kg: 13.5, volume_cbm: 0.04,
  status: 'loaded' as const, can_load: false, can_unload: true, blocker: null,
};

const DOSSIER = {
  reference: 'AIR-DSS-CDG-2026-002-A001', local_reference: 'A001',
  customer: { name: 'Fatou' }, complete: true, packages: [COLIS],
};

const DETAIL = { ...ENTETE, summary: RESUME, shipments: [DOSSIER] };

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
});

describe('le contrat du chargement', () => {
  it('accepte le DTO du serveur, tel quel', () => {
    expect(detailChargement.parse(DETAIL)).toEqual(DETAIL);
    expect(listeChargement.parse({ consolidations: [{ ...ENTETE, summary: RESUME }] }))
      .toEqual({ consolidations: [{ ...ENTETE, summary: RESUME }] });
  });

  it('refuse un champ de plus, plutôt que de l’ignorer', () => {
    expect(() => detailChargement.parse({ ...DETAIL, percent_loaded: 66 })).toThrow();
    expect(() => detailChargement.parse({
      ...DETAIL, summary: { ...RESUME, completion_rate: 0.66 },
    })).toThrow();
  });

  it('n’a aucun taux ni pourcentage dans le résumé', () => {
    for (const cle of Object.keys(RESUME)) {
      expect(cle).not.toMatch(/percent|ratio|rate/);
    }
  });

  it('un dossier repris peut n’avoir aucune référence externe', () => {
    const repris = { ...DETAIL, shipments: [{ ...DOSSIER, reference: '' }] };
    expect(() => detailChargement.parse(repris)).not.toThrow();
  });

  it('refuse un statut de colis que le serveur ne produit pas', () => {
    expect(() => detailChargement.parse({
      ...DETAIL,
      shipments: [{ ...DOSSIER, packages: [{ ...COLIS, status: 'en_route' }] }],
    })).toThrow();
  });

  it('la demande ne porte jamais de quantité', () => {
    const demande = {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      action: 'load' as const,
      package_reference: COLIS.reference,
    };
    expect(demandeChargement.parse(demande)).toEqual(demande);
    expect(() => demandeChargement.parse({ ...demande, quantity: 1 })).toThrow();
    expect(() => demandeChargement.parse({ ...demande, action: 'depart' })).toThrow();
    expect(() => demandeChargement.parse({ ...demande, request_uuid: 'x' })).toThrow();
  });

  it('la réponse d’un geste rend le départ entier, recalculé', () => {
    const applique = { replayed: false, loading: DETAIL };
    expect(chargementApplique.parse(applique)).toEqual(applique);
    expect(() => chargementApplique.parse({ replayed: false })).toThrow();
  });
});

describe('la référence de départ', () => {
  it('accepte ce que la production contient', () => {
    expect(normaliserReferenceDepart('AIR-DSS-CDG-2026-002'))
      .toBe('AIR-DSS-CDG-2026-002');
    expect(normaliserReferenceDepart('SEA_DKR_LEH_2026_001'))
      .toBe('SEA_DKR_LEH_2026_001');
  });

  it('refuse sans jamais rogner : un lien fautif doit se voir', () => {
    for (const brute of [' AIR-DSS', 'AIR-DSS ', '', '../etc', 'A/B', 'A B',
                         'A--B', '-AIR', 'AIR-', 'AIR%2DDSS', 42, null,
                         undefined]) {
      expect(normaliserReferenceDepart(brute), String(brute)).toBeNull();
    }
  });

  it('refuse au-delà de la borne', () => {
    expect(normaliserReferenceDepart('A'.repeat(121))).toBeNull();
    expect(normaliserReferenceDepart('A'.repeat(120))).toBe('A'.repeat(120));
  });
});

describe('les appels', () => {
  it('la liste ne prend aucun paramètre', async () => {
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [] });
    await fetchLoadings('sid', 'cid');
    expect(vi.mocked(opsGet).mock.calls[0]?.[0]).toBe('loading/consolidations');
  });

  it('le détail vise la ressource du départ, sans réencodage', async () => {
    vi.mocked(opsGet).mockResolvedValue({ loading: DETAIL });
    await fetchLoading('AIR-DSS-CDG-2026-002', 'sid', 'cid');
    expect(vi.mocked(opsGet).mock.calls[0]?.[0])
      .toBe('loading/consolidations/AIR-DSS-CDG-2026-002');
  });

  it('une référence invalide n’atteint jamais le réseau', async () => {
    await expect(fetchLoading('../identity', 'sid', 'cid')).rejects.toThrow();
    expect(opsGet).not.toHaveBeenCalled();
    await expect(applyLoading('A B', {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      action: 'load', package_reference: COLIS.reference,
    }, 'sid', 'cid')).rejects.toThrow();
    expect(opsPost).not.toHaveBeenCalled();
  });

  it('le geste part en POST sur la même ressource', async () => {
    vi.mocked(opsPost).mockResolvedValue({ replayed: false, loading: DETAIL });
    const demande = {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      action: 'unload' as const, package_reference: COLIS.reference,
    };
    await applyLoading('AIR-DSS-CDG-2026-002', demande, 'sid', 'cid');
    expect(vi.mocked(opsPost).mock.calls[0]?.[0])
      .toBe('loading/consolidations/AIR-DSS-CDG-2026-002');
    expect(vi.mocked(opsPost).mock.calls[0]?.[1]).toEqual(demande);
  });
});
