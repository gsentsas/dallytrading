import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Le contrat de la fiche en lecture seule, dans les deux sens.
 *
 * `.strict()` est ici la garde principale : le DTO natif porte la
 * tarification, les transitions et la révision de chaque article. Le jour où
 * quelqu'un brancherait la fiche legacy sur cette projection-là, la lecture
 * doit tomber plutôt que de laisser descendre ce qu'elle contient.
 */

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn() };
});

const { opsGet } = await import('@/lib/auth/odoo-ops');
const { fetchLegacyIntake, ficheLegacy } = await import('@/lib/ops/legacy-intake');

const FICHE = {
  readonly: true as const,
  reference: 'AIR-DSS-CDG-2026-002-A015',
  local_reference: 'A015',
  state: 'goods_received',
  state_label: 'Goods received',
  transport_mode: 'air',
  direction: 'export',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  received_on: '2026-08-20',
  customer: { name: 'Awa Legacy', phone: '+221 77 400 11 22' },
  lines: [{
    description: 'Carton repris', goods_category: 'Divers',
    package_type: 'parcel', quantity: 2,
    announced_weight_kg: null, exact_weight_kg: 8,
    length_cm: null, width_cm: null, height_cm: null, volume_cbm: 0.02,
  }],
  totals: { lines_count: 1, weight_kg: 8, volume_cbm: 0.02 },
  payments: [{
    amount: 15000, currency_code: 'XOF', payment_date: '2026-08-20',
    payment_method: { code: 'cash', name: 'Espèces' },
    collector: 'Gilles', accounting_status: 'registered',
  }],
  payment_summary: [{ currency_code: 'XOF', amount: 15000 }],
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsGet).mockResolvedValue({ intake: FICHE });
});

describe('la lecture d’un dossier repris', () => {
  it('rend la fiche telle que le serveur la compose', async () => {
    const fiche = await fetchLegacyIntake(FICHE.reference, 'session', 'cid');
    expect(fiche.reference).toBe(FICHE.reference);
    expect(fiche.readonly).toBe(true);
    expect(fiche.totals.lines_count).toBe(1);
  });

  it('interroge la route dédiée, jamais celle de la fiche native', async () => {
    await fetchLegacyIntake(FICHE.reference, 'session', 'cid');
    expect(vi.mocked(opsGet).mock.calls[0]?.[0])
      .toBe(`intakes/${FICHE.reference}/legacy-detail`);
  });

  it('accepte une référence du format historique à barres verticales', () => {
    expect(() => ficheLegacy.parse({ ...FICHE, reference: 'SN-DK_FR-PA_004' }))
      .not.toThrow();
  });

  it('refuse une référence qui pourrait composer un chemin', async () => {
    for (const mauvaise of ['../autre', 'A001/../A002', 'A001?x=1', '']) {
      await expect(fetchLegacyIntake(mauvaise, 'session', 'cid')).rejects.toThrow();
    }
  });
});

describe('ce que le contrat refuse de laisser descendre', () => {
  it('fait tomber la lecture sur un champ de plus', () => {
    for (const surplus of [
      { editable: true },
      { allowed_transitions: ['preparing'] },
      { sync_source_key: 'sheets:1' },
      { id: 42 },
    ]) {
      expect(() => ficheLegacy.parse({ ...FICHE, ...surplus }),
             JSON.stringify(surplus)).toThrow();
    }
  });

  it('refuse un article qui porterait sa tarification', () => {
    const ligne = { ...FICHE.lines[0], transport_amount_eur: 12.5 };
    expect(() => ficheLegacy.parse({ ...FICHE, lines: [ligne] })).toThrow();
  });

  it('refuse un encaissement qui porterait sa référence', () => {
    // `_reference_publique()` rend la clé externe telle quelle hors `ops:`.
    const paiement = { ...FICHE.payments[0], reference: 'sheets:pay:abc' };
    expect(() => ficheLegacy.parse({ ...FICHE, payments: [paiement] })).toThrow();
  });

  it('refuse une fiche qui ne se déclarerait pas en lecture seule', () => {
    expect(() => ficheLegacy.parse({ ...FICHE, readonly: false })).toThrow();
  });

  it('n’expose aucune section d’événements', () => {
    expect(Object.keys(ficheLegacy.shape)).not.toContain('events');
    expect(() => ficheLegacy.parse({ ...FICHE, events: [] })).toThrow();
  });
});
