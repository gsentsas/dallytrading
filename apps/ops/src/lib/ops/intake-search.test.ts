import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGetQuery: vi.fn() };
});

const { opsGetQuery } = await import('@/lib/auth/odoo-ops');
const { searchIntakes } = await import('@/lib/ops/intake-search');

const ITEM = {
  reference: 'AIR-DSS-CDG-2026-002-A001',
  local_reference: 'A001',
  customer_name: 'Mayram Soumaré',
  customer_phone: '+221 77 123 45 67',
  state: 'goods_received',
  transport_mode: 'air',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  received_on: '2026-08-29',
  detail_access: 'full',
  detail_access_reason: null,
};

beforeEach(() => { vi.mocked(opsGetQuery).mockReset(); });
afterEach(() => { vi.restoreAllMocks(); });

describe('contrat de la recherche de dossier', () => {
  it('interroge « intakes/search » et transmet la requête', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({ items: [ITEM], has_more: false });
    await searchIntakes({ q: 'A001' }, 'session', 'correlation');
    expect(opsGetQuery).toHaveBeenCalledWith(
      'intakes/search', { q: 'A001' }, 'session', 'correlation');
  });

  it('ne transmet ni plafond ni curseur quand ils sont absents', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({ items: [], has_more: false });
    await searchIntakes({ q: 'Soumar' }, 'session', 'correlation');
    expect(vi.mocked(opsGetQuery).mock.calls[0]?.[1]).toEqual({ q: 'Soumar' });
  });

  it('accepte un dossier repris, ouvrable en lecture seule', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      items: [{
        ...ITEM, reference: 'A012', local_reference: '',
        detail_access: 'readonly', detail_access_reason: 'legacy_readonly',
      }],
      has_more: false,
    });
    const page = await searchIntakes({ q: 'A012' }, 'session', 'correlation');
    expect(page.items[0]?.detail_access).toBe('readonly');
    expect(page.items[0]?.detail_access_reason).toBe('legacy_readonly');
  });

  it('accepte un dossier sans référence globale, que rien ne peut ouvrir', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      items: [{
        ...ITEM, reference: '', local_reference: '',
        detail_access: 'unavailable', detail_access_reason: 'no_reference',
      }],
      has_more: false,
    });
    const page = await searchIntakes({ q: 'Soumare' }, 'session', 'correlation');
    expect(page.items[0]?.detail_access).toBe('unavailable');
    expect(page.items[0]?.detail_access_reason).toBe('no_reference');
  });

  it('refuse l’ancien motif, retiré avec la fiche en lecture seule', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      items: [{ ...ITEM, detail_access_reason: 'legacy_not_supported' }],
      has_more: false,
    });
    await expect(searchIntakes({ q: 'A012' }, 'session', 'correlation'))
      .rejects.toThrow();
  });

  it('refuse un champ inconnu plutôt que de le transmettre au navigateur', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      items: [{ ...ITEM, shipment_id: 688 }], has_more: false,
    });
    await expect(searchIntakes({ q: 'A001' }, 'session', 'correlation'))
      .rejects.toThrow();
  });

  it('M13 · refuse un curseur, fût-il opaque', async () => {
    // Un curseur exigerait une clé de parcours ; la seule qui soit totale est
    // `dally.shipment.id`, un identifiant de base. `.strict()` referme la
    // porte plutôt que de laisser le champ revenir sans décision.
    vi.mocked(opsGetQuery).mockResolvedValue({
      items: [ITEM], has_more: false, next_cursor: 'MTMxNA==',
    });
    await expect(searchIntakes({ q: 'A001' }, 'session', 'correlation'))
      .rejects.toThrow();
  });

  it('remonte le drapeau de troncature tel quel', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({ items: [ITEM], has_more: true });
    const page = await searchIntakes({ q: 'A0' }, 'session', 'correlation');
    expect(page.has_more).toBe(true);
  });

  it('refuse un accès détaillé inconnu', async () => {
    vi.mocked(opsGetQuery).mockResolvedValue({
      items: [{ ...ITEM, detail_access: 'partial' }], has_more: false,
    });
    await expect(searchIntakes({ q: 'A001' }, 'session', 'correlation'))
      .rejects.toThrow();
  });
});
