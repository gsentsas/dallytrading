import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn() };
});

const { opsGet, opsPost } = await import('@/lib/auth/odoo-ops');
const {
  demandeWave, fetchShipmentPayments, fetchWaveContext, recordWavePayment,
} = await import('@/lib/ops/wave-payments');

const UUID = '11111111-2222-4333-8444-555555555555';
const AXXX = 'AIR-DSS-CDG-TEST-001-A001';

const PAIEMENT = {
  reference: UUID,
  amount: 100000,
  currency_code: 'XOF',
  paid_at: '2026-08-28',
  payment_method: 'wave',
  beneficiary: 'Gilles',
  wave_reference: 'TWXYZ12345',
  note: '',
  accounting_status: 'pending' as const,
};

const CONTEXTE = {
  intake_reference: AXXX,
  customer_name: 'Aissatou Kandji',
  payment_method: 'wave' as const,
  beneficiary: 'Gilles',
  currencies: ['XOF'],
  payments: { items: [], summary: [] },
};

const DEMANDE = {
  request_uuid: UUID,
  amount: 100000,
  currency: 'XOF',
  wave_reference: 'TWXYZ12345',
  paid_at: '2026-08-28',
  note: '',
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
});

describe('ce que le navigateur a le droit de demander', () => {
  it('accepte une demande complète', () => {
    expect(demandeWave.safeParse(DEMANDE).success).toBe(true);
  });

  it('accepte une demande sans référence Wave', () => {
    expect(demandeWave.safeParse({ ...DEMANDE, wave_reference: null }).success)
      .toBe(true);
  });

  it.each([
    'payment_method', 'method', 'beneficiary', 'beneficiary_user_id',
    'partner_id', 'customer_id', 'user_id', 'shipment_id', 'collected_by_name',
    'source', 'state', 'invoice_id', 'company_id',
  ])('refuse la clé %s, décidée par le serveur', (cle) => {
    expect(demandeWave.safeParse({ ...DEMANDE, [cle]: 'x' }).success).toBe(false);
  });

  it('refuse même un moyen de paiement qui porterait la bonne valeur', () => {
    // Accepter « wave » ferait croire au client qu'il le choisit.
    expect(demandeWave.safeParse({ ...DEMANDE, payment_method: 'wave' }).success)
      .toBe(false);
    expect(demandeWave.safeParse({ ...DEMANDE, beneficiary: 'Gilles' }).success)
      .toBe(false);
  });

  it.each([0, -1, -100000])('refuse le montant %s', (valeur) => {
    expect(demandeWave.safeParse({ ...DEMANDE, amount: valeur }).success).toBe(false);
  });

  it('refuse une date mal formée', () => {
    expect(demandeWave.safeParse({ ...DEMANDE, paid_at: '28/08/2026' }).success)
      .toBe(false);
  });

  it('exige un identifiant de demande', () => {
    const partiel: Record<string, unknown> = { ...DEMANDE };
    delete partiel.request_uuid;
    expect(demandeWave.safeParse(partiel).success).toBe(false);
  });
});

describe('contexte du dossier', () => {
  it('vise la ressource du dossier par sa référence publique', async () => {
    vi.mocked(opsGet).mockResolvedValue(CONTEXTE);
    await fetchWaveContext(AXXX, 'sX', 'corr');
    expect(opsGet).toHaveBeenCalledWith(
      `shipments/${AXXX}/wave-context`, 'sX', 'corr');
  });

  it('rend le bénéficiaire et le moyen imposés', async () => {
    vi.mocked(opsGet).mockResolvedValue(CONTEXTE);
    const contexte = await fetchWaveContext(AXXX, 'sX', 'corr');
    expect(contexte.beneficiary).toBe('Gilles');
    expect(contexte.payment_method).toBe('wave');
  });

  it('refuse un contexte où le moyen ne serait pas Wave', async () => {
    vi.mocked(opsGet).mockResolvedValue({ ...CONTEXTE, payment_method: 'cash' });
    await expect(fetchWaveContext(AXXX, 'sX', 'corr')).rejects.toThrow();
  });

  it.each(['partner_id', 'shipment_id', 'company_id', 'beneficiary_user_id'])(
    'refuse un contexte portant %s', async (cle) => {
      vi.mocked(opsGet).mockResolvedValue({ ...CONTEXTE, [cle]: 42 });
      await expect(fetchWaveContext(AXXX, 'sX', 'corr')).rejects.toThrow();
    });
});

describe('enregistrement', () => {
  it('vise la ressource des encaissements du dossier', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', payment: PAIEMENT });
    await recordWavePayment(AXXX, DEMANDE, 'sX', 'corr');
    expect(opsPost).toHaveBeenCalledWith(
      `shipments/${AXXX}/payments`, DEMANDE, 'sX', 'corr');
  });

  it('rend l’encaissement, son bénéficiaire et son verdict comptable', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', payment: PAIEMENT });
    const resultat = await recordWavePayment(AXXX, DEMANDE, 'sX', 'corr');
    expect(resultat.payment.beneficiary).toBe('Gilles');
    expect(resultat.payment.payment_method).toBe('wave');
    expect(resultat.payment.accounting_status).toBe('pending');
  });

  it('accepte un rejeu', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'replayed', payment: PAIEMENT });
    await expect(recordWavePayment(AXXX, DEMANDE, 'sX', 'corr'))
      .resolves.toHaveProperty('status', 'replayed');
  });

  it.each(['collection_id', 'account_payment_id', 'partner_id', 'invoice_id',
           'journal_id', 'error_message', 'shipment_id'])(
    'refuse une réponse portant %s', async (cle) => {
      vi.mocked(opsPost).mockResolvedValue({
        status: 'created', payment: { ...PAIEMENT, [cle]: 42 },
      });
      await expect(recordWavePayment(AXXX, DEMANDE, 'sX', 'corr')).rejects.toThrow();
    });

  it('refuse un état brut du moteur comme verdict', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'created', payment: { ...PAIEMENT, accounting_status: 'error' },
    });
    await expect(recordWavePayment(AXXX, DEMANDE, 'sX', 'corr')).rejects.toThrow();
  });
});

describe('lecture des encaissements d’un dossier', () => {
  it('rend un total par devise, jamais un total unique', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      intake_reference: AXXX,
      items: [PAIEMENT],
      summary: [
        { currency_code: 'EUR', amount: 40 },
        { currency_code: 'XOF', amount: 100000 },
      ],
    });
    const liste = await fetchShipmentPayments(AXXX, 'sX', 'corr');
    expect(liste.summary).toHaveLength(2);
  });

  it('refuse un résumé qui porterait un montant converti', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      intake_reference: AXXX, items: [],
      summary: [{ currency_code: 'XOF', amount: 100000, amount_eur: 152 }],
    });
    await expect(fetchShipmentPayments(AXXX, 'sX', 'corr')).rejects.toThrow();
  });
});
