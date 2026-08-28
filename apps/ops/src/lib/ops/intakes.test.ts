import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<
    typeof import('@/lib/auth/odoo-ops')
  >();
  return {
    ...original,
    opsGet: vi.fn(),
    opsPost: vi.fn(),
  };
});

const { opsGet, opsPost } = await import(
  '@/lib/auth/odoo-ops'
);
const {
  createIntake,
  demandeIntake,
  fetchTariffFamilies,
} = await import('@/lib/ops/intakes');

const DEMANDE = {
  request_uuid: '11111111-2222-4333-8444-555555555555',
  consolidation_reference: 'AIR-DSS-CDG-2026-002',
  customer_reference: 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
  received_on: '2026-08-28',
  line: {
    line_uuid: '99999999-8888-4777-8666-555555555555',
    package_type: 'parcel' as const,
    goods_category: 'Non alimentaire',
    description: 'Savon',
    quantity: 1,
    announced_weight_kg: 13,
    exact_weight_kg: 13.5,
    length_cm: null,
    width_cm: null,
    height_cm: null,
    billing_method: 'real' as const,
    tariff_family_code: 'non_food',
    customs_value_xof: 25000,
  },
};

const RESULTAT = {
  status: 'created',
  intake: {
    reference: 'AIR-DSS-CDG-2026-002-A001',
    local_reference: 'A001',
    consolidation_reference: 'AIR-DSS-CDG-2026-002',
    state: 'goods_received',
    received_on: '2026-08-28',
    line: {
      reference: DEMANDE.line.line_uuid,
      description: 'Savon',
      goods_category: 'Non alimentaire',
      quantity: 1,
      exact_weight_kg: 13.5,
      volume_cbm: 0,
      billing_method: 'real',
      tariff_family_code: 'non_food',
      customs_value_xof: 25000,
      pricing_status: 'automatic',
      billable_weight_kg: 13.5,
      applied_unit_price_eur: 5,
      transport_amount_eur: 67.5,
    },
    totals: {
      weight_kg: 13.5,
      volume_cbm: 0,
      transport_amount_eur: 67.5,
    },
  },
};

describe('contrat intake entrant', () => {
  it('accepte la charge phase 1 exacte', () => {
    expect(demandeIntake.parse(DEMANDE)).toEqual(DEMANDE);
  });

  it.each([
    'partner_id',
    'shipment_id',
    'package_id',
    'consolidation_id',
    'external_reference',
    'collection_local_ref',
    'transport_mode',
    'direction',
    'origin',
    'state',
  ])('refuse la clé serveur %s', (cle) => {
    expect(
      demandeIntake.safeParse({ ...DEMANDE, [cle]: 1 }).success,
    ).toBe(false);
  });

  it.each([
    'external_line_key',
    'manual_unit_price_eur',
    'pricing_reason',
    'pricing_type',
  ])('refuse la clé ligne serveur %s', (cle) => {
    expect(
      demandeIntake.safeParse({
        ...DEMANDE,
        line: { ...DEMANDE.line, [cle]: 1 },
      }).success,
    ).toBe(false);
  });

  it('exige poids, douane, famille et quantité positifs', () => {
    for (const ligne of [
      { exact_weight_kg: 0 },
      { customs_value_xof: 0 },
      { tariff_family_code: '' },
      { quantity: 0 },
    ]) {
      expect(
        demandeIntake.safeParse({
          ...DEMANDE,
          line: { ...DEMANDE.line, ...ligne },
        }).success,
      ).toBe(false);
    }
  });

  it('impose dimensions all-or-none et volumétriques', () => {
    expect(
      demandeIntake.safeParse({
        ...DEMANDE,
        line: { ...DEMANDE.line, length_cm: 10 },
      }).success,
    ).toBe(false);
    expect(
      demandeIntake.safeParse({
        ...DEMANDE,
        line: {
          ...DEMANDE.line,
          billing_method: 'volumetric',
        },
      }).success,
    ).toBe(false);
  });
});

describe('contrats de sortie', () => {
  it('relaie uniquement le DTO public strict', async () => {
    vi.mocked(opsPost).mockResolvedValue(RESULTAT);
    await expect(
      createIntake(DEMANDE, 'sX', 'corr'),
    ).resolves.toEqual(RESULTAT);
  });

  it('refuse tout identifiant Odoo ajouté au DTO', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      ...RESULTAT,
      shipment_id: 42,
    });
    await expect(
      createIntake(DEMANDE, 'sX', 'corr'),
    ).rejects.toThrow();
  });

  it('accepte À définir sans transformer zéro en prix', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      ...RESULTAT,
      intake: {
        ...RESULTAT.intake,
        line: {
          ...RESULTAT.intake.line,
          pricing_status: 'manual_required',
          applied_unit_price_eur: null,
          transport_amount_eur: null,
        },
        totals: {
          ...RESULTAT.intake.totals,
          transport_amount_eur: null,
        },
      },
    });
    const resultat = await createIntake(
      DEMANDE, 'sX', 'corr',
    );
    expect(
      resultat.intake.line.transport_amount_eur,
    ).toBeNull();
  });

  it('ne laisse sortir que code et nom des familles', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      tariff_families: [{
        code: 'non_food',
        name: 'Non alimentaire',
      }],
    });
    await expect(
      fetchTariffFamilies('sX', 'corr'),
    ).resolves.toEqual([{
      code: 'non_food',
      name: 'Non alimentaire',
    }]);
    vi.mocked(opsGet).mockResolvedValue({
      tariff_families: [{
        code: 'x',
        name: 'X',
        price_per_kg_eur: 5,
      }],
    });
    await expect(
      fetchTariffFamilies('sX', 'corr'),
    ).rejects.toThrow();
  });
});

