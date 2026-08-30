import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn(), opsPut: vi.fn() };
});

const { opsGet, opsPost, opsPut } = await import('@/lib/auth/odoo-ops');
const { addLine, demandeAjout, demandeCorrection, fetchIntake, saisieLigne, updateLine } =
  await import('@/lib/ops/intake-lines');

const LIGNE = {
  line_uuid: '22222222-3333-4444-8555-666666666666',
  package_type: 'parcel' as const,
  goods_category: 'Non alimentaire',
  description: 'Savon',
  quantity: 1,
  announced_weight_kg: null,
  exact_weight_kg: 13.5,
  length_cm: null,
  width_cm: null,
  height_cm: null,
  billing_method: 'real' as const,
  tariff_family_code: 'non_food',
  customs_value_xof: 25000,
};

const LIGNE_LUE = {
  ...LIGNE,
  reference: LIGNE.line_uuid,
  revision: 'abc123',
  volume_cbm: 0,
  pricing_status: 'automatic' as const,
  billable_weight_kg: 13.5,
  applied_unit_price_eur: 5,
  transport_amount_eur: 67.5,
};
delete (LIGNE_LUE as Record<string, unknown>).line_uuid;

const DOSSIER = {
  reference: 'AIR-DSS-CDG-2026-002-A001',
  local_reference: 'A001',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  state: 'goods_received',
  received_on: '2026-08-28',
  customer: { name: 'Aissatou Kandji' },
  editable: true,
  edit_block_reason: null,
  lines: [LIGNE_LUE],
  totals: {
    lines_count: 1, weight_kg: 13.5, volume_cbm: 0,
    transport_amount_eur: 67.5, pricing_complete: true,
  },
  payments: [],
  payment_summary: [],
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
  vi.mocked(opsPut).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('lecture du dossier', () => {
  it('vise la ressource du dossier', async () => {
    vi.mocked(opsGet).mockResolvedValue({ intake: DOSSIER });
    await fetchIntake('AIR-DSS-CDG-2026-002-A001', 'sX', 'corr');
    expect(opsGet).toHaveBeenCalledWith(
      'intakes/AIR-DSS-CDG-2026-002-A001', 'sX', 'corr');
  });

  it('rend le dossier et ses articles', async () => {
    vi.mocked(opsGet).mockResolvedValue({ intake: DOSSIER });
    const dossier = await fetchIntake('AIR-1', 'sX', 'corr');
    expect(dossier.lines).toHaveLength(1);
    expect(dossier.totals.pricing_complete).toBe(true);
  });

  it('accepte un total indéfini tant qu’une ligne n’est pas tarifée', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      intake: {
        ...DOSSIER,
        totals: { ...DOSSIER.totals, transport_amount_eur: null, pricing_complete: false },
      },
    });
    const dossier = await fetchIntake('AIR-1', 'sX', 'corr');
    // `null` et non `0` : un total partiel n'est pas un prix.
    expect(dossier.totals.transport_amount_eur).toBeNull();
  });

  it('refuse un dossier qui porterait un identifiant Odoo', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      intake: { ...DOSSIER, shipment_id: 42 },
    });
    await expect(fetchIntake('AIR-1', 'sX', 'corr')).rejects.toThrow();
  });

  it('refuse un client qui porterait autre chose que son nom', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      intake: { ...DOSSIER, customer: { name: 'A', phone: '+221 77' } },
    });
    // Le contrat referme ici : le téléphone n'atteint pas le navigateur.
    await expect(fetchIntake('AIR-1', 'sX', 'corr')).rejects.toThrow();
  });

  it('refuse un motif de blocage inconnu', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      intake: { ...DOSSIER, editable: false, edit_block_reason: 'parce_que' },
    });
    await expect(fetchIntake('AIR-1', 'sX', 'corr')).rejects.toThrow();
  });
});

describe('ce que le navigateur a le droit de demander', () => {
  it('accepte un ajout complet', () => {
    expect(demandeAjout.safeParse({
      request_uuid: '11111111-2222-4333-8444-555555555555', line: LIGNE,
    }).success).toBe(true);
  });

  it('exige la version lue pour une correction', () => {
    expect(demandeCorrection.safeParse({
      request_uuid: '11111111-2222-4333-8444-555555555555', line: LIGNE,
    }).success).toBe(false);
  });

  it.each(['package_id', 'shipment_id', 'external_line_key', 'manual_unit_price_eur'])(
    'refuse la clé %s', (cle) => {
      expect(saisieLigne.safeParse({ ...LIGNE, [cle]: 1 }).success).toBe(false);
    });

  it('refuse un poids nul', () => {
    expect(saisieLigne.safeParse({ ...LIGNE, exact_weight_kg: 0 }).success).toBe(false);
  });

  it('refuse une valeur déclarée nulle', () => {
    expect(saisieLigne.safeParse({ ...LIGNE, customs_value_xof: 0 }).success).toBe(false);
  });

  it('refuse une seule dimension', () => {
    expect(saisieLigne.safeParse({ ...LIGNE, length_cm: 50 }).success).toBe(false);
  });

  it('refuse un volumétrique sans dimensions', () => {
    expect(saisieLigne.safeParse({
      ...LIGNE, billing_method: 'volumetric',
    }).success).toBe(false);
  });

  it('accepte les trois dimensions ensemble', () => {
    expect(saisieLigne.safeParse({
      ...LIGNE, length_cm: 50, width_cm: 40, height_cm: 30,
    }).success).toBe(true);
  });
});

describe('mutations', () => {
  it('ajoute un article sur la ressource du dossier', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'added', intake: DOSSIER, line: LIGNE_LUE,
    });
    const demande = {
      request_uuid: '11111111-2222-4333-8444-555555555555', line: LIGNE,
    };
    await addLine('AIR-1-A001', demande, 'sX', 'corr');
    expect(opsPost).toHaveBeenCalledWith(
      'intakes/AIR-1-A001/lines', demande, 'sX', 'corr');
  });

  it('corrige un article par remplacement', async () => {
    vi.mocked(opsPut).mockResolvedValue({
      status: 'updated', intake: DOSSIER, line: LIGNE_LUE,
    });
    const demande = {
      request_uuid: '11111111-2222-4333-8444-555555555555',
      expected_revision: 'abc123', line: LIGNE,
    };
    await updateLine('AIR-1-A001', LIGNE.line_uuid, demande, 'sX', 'corr');
    expect(opsPut).toHaveBeenCalledWith(
      `intakes/AIR-1-A001/lines/${LIGNE.line_uuid}`, demande, 'sX', 'corr');
  });

  it('refuse un statut de mutation inconnu', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'deleted', intake: DOSSIER, line: LIGNE_LUE,
    });
    await expect(addLine('AIR-1', {
      request_uuid: '11111111-2222-4333-8444-555555555555', line: LIGNE,
    }, 'sX', 'corr')).rejects.toThrow();
  });
});
