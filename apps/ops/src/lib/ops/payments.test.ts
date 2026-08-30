import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsPost: vi.fn() };
});

const { opsGet, opsPost } = await import('@/lib/auth/odoo-ops');
const { demandePaiement, fetchPaymentChannels, recordPayment } =
  await import('@/lib/ops/payments');

const CANAL = { code: 'wave', name: 'Wave', currency_code: 'XOF' };
const PAIEMENT = {
  reference: '11111111-2222-4333-8444-555555555555',
  amount: 44280,
  currency_code: 'XOF',
  payment_date: '2026-08-28',
  payment_method: { code: 'wave', name: 'Wave' },
  collector: 'Gilles',
  accounting_status: 'pending' as const,
};
const DEMANDE = {
  request_uuid: '11111111-2222-4333-8444-555555555555',
  amount: 44280,
  payment_date: '2026-08-28',
  payment_method: 'wave',
  currency_code: 'XOF',
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsPost).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('canaux de paiement', () => {
  it('vise la ressource des canaux', async () => {
    vi.mocked(opsGet).mockResolvedValue({ channels: [CANAL] });
    await fetchPaymentChannels('sX', 'corr');
    expect(opsGet).toHaveBeenCalledWith('payment-channels', 'sX', 'corr');
  });

  it('rend le code, le nom et la devise', async () => {
    vi.mocked(opsGet).mockResolvedValue({ channels: [CANAL] });
    await expect(fetchPaymentChannels('sX', 'corr')).resolves.toEqual([CANAL]);
  });

  it('refuse un canal qui porterait sa configuration comptable', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      channels: [{ ...CANAL, journal_id: 3, payment_method_line_id: 7 }],
    });
    // La configuration comptable de DallyTrading n'a rien à faire sur un
    // téléphone d'entrepôt.
    await expect(fetchPaymentChannels('sX', 'corr')).rejects.toThrow();
  });
});

describe('ce que le navigateur a le droit de demander', () => {
  it('accepte une demande complète', () => {
    expect(demandePaiement.safeParse(DEMANDE).success).toBe(true);
  });

  it.each(['collected_by', 'collector', 'source', 'external_payment_key',
           'shipment_id', 'collection_id'])(
    'refuse la clé %s', (cle) => {
      expect(demandePaiement.safeParse({ ...DEMANDE, [cle]: 'x' }).success).toBe(false);
    });

  it.each([0, -1, -44280])('refuse le montant %s', (montant) => {
    expect(demandePaiement.safeParse({ ...DEMANDE, amount: montant }).success).toBe(false);
  });

  it('refuse une date mal formée', () => {
    expect(demandePaiement.safeParse({
      ...DEMANDE, payment_date: '28/08/2026',
    }).success).toBe(false);
  });

  it('exige un identifiant de demande', () => {
    const partiel: Record<string, unknown> = { ...DEMANDE };
    delete partiel.request_uuid;
    expect(demandePaiement.safeParse(partiel).success).toBe(false);
  });
});

describe('enregistrement', () => {
  it('vise la ressource des encaissements du dossier', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', payment: PAIEMENT });
    await recordPayment('AIR-1-A001', DEMANDE, 'sX', 'corr');
    expect(opsPost).toHaveBeenCalledWith(
      'intakes/AIR-1-A001/payments', DEMANDE, 'sX', 'corr');
  });

  it('rend le paiement et son statut comptable', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'created', payment: PAIEMENT });
    const resultat = await recordPayment('AIR-1', DEMANDE, 'sX', 'corr');
    expect(resultat.payment.accounting_status).toBe('pending');
    expect(resultat.payment.collector).toBe('Gilles');
  });

  it('accepte un rejeu', async () => {
    vi.mocked(opsPost).mockResolvedValue({ status: 'replayed', payment: PAIEMENT });
    const resultat = await recordPayment('AIR-1', DEMANDE, 'sX', 'corr');
    expect(resultat.status).toBe('replayed');
  });

  it.each(['registered', 'pending', 'needs_review'])(
    'accepte le statut comptable %s', async (statut) => {
      vi.mocked(opsPost).mockResolvedValue({
        status: 'created', payment: { ...PAIEMENT, accounting_status: statut },
      });
      await expect(recordPayment('AIR-1', DEMANDE, 'sX', 'corr')).resolves.toBeTruthy();
    });

  it('refuse un état brut du moteur comme statut', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'created', payment: { ...PAIEMENT, accounting_status: 'error' },
    });
    await expect(recordPayment('AIR-1', DEMANDE, 'sX', 'corr')).rejects.toThrow();
  });

  it('refuse une réponse qui porterait un message comptable', async () => {
    vi.mocked(opsPost).mockResolvedValue({
      status: 'created',
      payment: { ...PAIEMENT, error_message: 'journal BNK1 introuvable' },
    });
    await expect(recordPayment('AIR-1', DEMANDE, 'sX', 'corr')).rejects.toThrow();
  });

  it.each(['collection_id', 'account_payment_id', 'invoice_id', 'journal_id'])(
    'refuse une réponse portant %s', async (cle) => {
      vi.mocked(opsPost).mockResolvedValue({
        status: 'created', payment: { ...PAIEMENT, [cle]: 42 },
      });
      await expect(recordPayment('AIR-1', DEMANDE, 'sX', 'corr')).rejects.toThrow();
    });
});
