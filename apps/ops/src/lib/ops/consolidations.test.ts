import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn() };
});

const { opsGet } = await import('@/lib/auth/odoo-ops');
const { fetchConsolidations } = await import('@/lib/ops/consolidations');

const AERIEN = {
  reference: 'AIR-DSS-CDG-2026-002',
  transport_mode: 'air',
  direction: 'export',
  origin: { country_code: 'SN', city: 'Dakar', location: 'DSS' },
  destination: { country_code: 'FR', city: 'Paris', location: 'CDG' },
  collection_close_on: '2026-09-03',
  scheduled_departure: '2026-09-05T10:00:00Z',
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('lecture des départs', () => {
  it('demande la ressource « consolidations » et rien d’autre', async () => {
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [] });
    await fetchConsolidations('session-abc', 'corr');
    // Le nom, jamais le chemin : le préfixe /api/v1/ops/ est ajouté par la
    // passerelle, ce qui rend la sortie du périmètre impossible à écrire.
    expect(opsGet).toHaveBeenCalledWith('consolidations', 'session-abc', 'corr');
  });

  it('rend la liste telle que le serveur l’a ordonnée', async () => {
    const second = { ...AERIEN, reference: 'SEA-DKR-LEH-2026-001', transport_mode: 'sea' };
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [AERIEN, second] });
    const liste = await fetchConsolidations('s', 'corr');
    // Retrier ici ferait diverger ce que l'opérateur voit de ce que le serveur
    // a décidé.
    expect(liste.map((c) => c.reference)).toEqual([
      'AIR-DSS-CDG-2026-002',
      'SEA-DKR-LEH-2026-001',
    ]);
  });

  it('accepte une liste vide', async () => {
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [] });
    await expect(fetchConsolidations('s', 'corr')).resolves.toEqual([]);
  });

  it('accepte des dates absentes', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidations: [{ ...AERIEN, collection_close_on: null, scheduled_departure: null }],
    });
    const [entree] = await fetchConsolidations('s', 'corr');
    expect(entree?.scheduled_departure).toBeNull();
    expect(entree?.collection_close_on).toBeNull();
  });
});

describe('le contrat se referme ici', () => {
  it('laisse au vestiaire tout champ qu’Odoo ajouterait', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidations: [{
        ...AERIEN,
        id: 42,
        mawb_number: '074-12345678',
        shipper_label: 'Expéditeur interne',
        client_weight_kg: 812.5,
      }],
    });
    const [entree] = await fetchConsolidations('s', 'corr');
    // Un champ qui n'arrive jamais jusqu'à la page ne peut pas fuiter dans une
    // capture d'écran ni un rapport de bogue.
    expect(Object.keys(entree ?? {}).sort()).toEqual([
      'collection_close_on', 'destination', 'direction', 'origin',
      'reference', 'scheduled_departure', 'transport_mode',
    ]);
    expect(JSON.stringify(entree)).not.toContain('074-12345678');
  });

  it('retire aussi les champs ajoutés dans une origine ou une destination', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidations: [{ ...AERIEN, origin: { ...AERIEN.origin, notes: 'interne' } }],
    });
    const [entree] = await fetchConsolidations('s', 'corr');
    expect(Object.keys(entree?.origin ?? {}).sort()).toEqual(['city', 'country_code', 'location']);
  });

  it('refuse un mode de transport hors du périmètre colis', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      consolidations: [{ ...AERIEN, transport_mode: 'road' }],
    });
    // Phase 1 : uniquement des colis. Si le routier arrivait malgré le filtre
    // serveur, mieux vaut échouer que l'afficher.
    await expect(fetchConsolidations('s', 'corr')).rejects.toThrow();
  });

  it('refuse une réponse dont la forme n’est pas celle du contrat', async () => {
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [{ reference: 'AIR-1' }] });
    await expect(fetchConsolidations('s', 'corr')).rejects.toThrow();
  });

  it('refuse une référence vide', async () => {
    vi.mocked(opsGet).mockResolvedValue({ consolidations: [{ ...AERIEN, reference: '' }] });
    await expect(fetchConsolidations('s', 'corr')).rejects.toThrow();
  });
});
