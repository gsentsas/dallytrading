/**
 * Le contrat du reçu, éprouvé sur ce qu'il refuse.
 *
 * Un contrat souple laisserait passer, un jour, un identifiant interne dans un
 * document que le client emporte. Ces tests portent donc surtout sur les
 * charges utiles qui doivent échouer.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/odoo-ops', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/auth/odoo-ops')>();
  return { ...original, opsGet: vi.fn(), opsGetDocument: vi.fn() };
});

const { opsGet, opsGetDocument } = await import('@/lib/auth/odoo-ops');
const { fetchReceipt, fetchReceiptPdf, nomFichierRecu, recu } =
  await import('@/lib/ops/receipts');

const AXXX = 'AIR-DSS-CDG-TEST-001-A001';

const RECU = {
  document: {
    title: 'REÇU DE PRISE EN CHARGE',
    reference: AXXX,
    generated_at: '2026-08-30T09:15',
  },
  company: {
    name: 'DallyTrading', phone: '+221770000000', email: 'contact@example.test',
    address: 'Dakar', vat: '',
  },
  reference: AXXX,
  local_reference: 'DK-014',
  received_on: '2026-08-30',
  state: 'draft',
  transport_mode: 'air',
  transport_mode_label: 'Aérien',
  consolidation: { reference: 'AIR-DSS-CDG-TEST-001', origin: 'Dakar', destination: 'Paris' },
  customer: {
    name: 'Aissatou Kandji', phone: '+221770000009',
    email: 'aissatou@example.test', address: 'Rue 10 Dakar',
  },
  articles: [{
    description: 'Épices', goods_category: 'Alimentaire', quantity: 1,
    exact_weight_kg: 13.5, exact_weight_display: '13,5 kg',
    billable_weight_kg: 13.5, dimensions: '',
    customs_value_xof: 25000, tariff_family: 'Alimentaire standard',
    applied_unit_price_eur: 5, transport_amount_eur: 67.5,
    applied_unit_price_display: '5,00 €', transport_amount_display: '67,50 €',
  }],
  totals: {
    articles_count: 1, weight_kg: 13.5, weight_display: '13,5 kg',
    transport_amount_eur: 67.5, transport_amount_display: '67,50 €',
    currency_code: 'EUR',
    paid: [{ currency_code: 'XOF', amount: 100000, display: '100 000 FCFA' }],
    balance_eur: null, balance_display: '', balance_reason: 'currency_mismatch' as const,
  },
  payments: [{
    date: '2026-08-30', amount: 100000, currency_code: 'XOF', method: 'Wave',
    collected_by: 'Gilles', wave_reference: 'TWXYZ12345',
    amount_display: '100 000 FCFA',
  }],
  operator: { name: 'Gilles Sène' },
  invoice_number: '',
};

beforeEach(() => {
  vi.mocked(opsGet).mockReset();
  vi.mocked(opsGetDocument).mockReset();
});

describe('ce que le reçu a le droit de contenir', () => {
  it('accepte un reçu complet', () => {
    expect(recu.safeParse(RECU).success).toBe(true);
  });

  it('refuse toute clé qui n’est pas au contrat', () => {
    for (const intrus of [
      { partner_id: 42 }, { shipment_id: 7 }, { invoice_id: 9 },
      { sync_source_key: 'ops:x' }, { request_uuid: 'x' }, { api_key: 'x' },
    ]) {
      expect(recu.safeParse({ ...RECU, ...intrus }).success).toBe(false);
    }
  });

  it('refuse un identifiant interne glissé dans le client', () => {
    expect(recu.safeParse({
      ...RECU, customer: { ...RECU.customer, id: 51 },
    }).success).toBe(false);
  });

  it('refuse un identifiant interne glissé dans un paiement', () => {
    expect(recu.safeParse({
      ...RECU,
      payments: [{ ...RECU.payments[0], collection_id: 3 }],
    }).success).toBe(false);
  });

  it('accepte l’absence de prix, qui n’est pas un prix nul', () => {
    const sansPrix = {
      ...RECU,
      articles: [{
        ...RECU.articles[0],
        applied_unit_price_eur: null, transport_amount_eur: null,
        applied_unit_price_display: '', transport_amount_display: '',
      }],
      totals: {
        ...RECU.totals, transport_amount_eur: null, transport_amount_display: '',
        balance_reason: 'pricing_incomplete' as const,
      },
    };
    expect(recu.safeParse(sansPrix).success).toBe(true);
  });

  it('accepte un solde exact, motif absent', () => {
    expect(recu.safeParse({
      ...RECU,
      totals: {
        ...RECU.totals, balance_eur: 27.5, balance_display: '27,50 €',
        balance_reason: null,
      },
    }).success).toBe(true);
  });

  it('refuse un motif de solde inventé', () => {
    expect(recu.safeParse({
      ...RECU, totals: { ...RECU.totals, balance_reason: 'approximatif' },
    }).success).toBe(false);
  });

  it('refuse un reçu sans référence', () => {
    expect(recu.safeParse({ ...RECU, reference: '' }).success).toBe(false);
  });

  it('accepte un dossier sans aucun paiement', () => {
    expect(recu.safeParse({
      ...RECU,
      payments: [],
      totals: { ...RECU.totals, paid: [], balance_eur: 67.5,
                balance_display: '67,50 €', balance_reason: null },
    }).success).toBe(true);
  });
});

describe('la lecture du reçu', () => {
  it('demande la ressource du dossier et rend le reçu', async () => {
    vi.mocked(opsGet).mockResolvedValue({ receipt: RECU });
    const lu = await fetchReceipt(AXXX, 'sid', 'cid');
    expect(opsGet).toHaveBeenCalledWith(
      `intakes/${AXXX}/receipt`, 'sid', 'cid');
    expect(lu.reference).toBe(AXXX);
    expect(lu.customer.name).toBe('Aissatou Kandji');
  });

  it('échoue plutôt que de laisser passer une charge inattendue', async () => {
    vi.mocked(opsGet).mockResolvedValue({
      receipt: { ...RECU, partner_id: 42 },
    });
    await expect(fetchReceipt(AXXX, 'sid', 'cid')).rejects.toThrow();
  });

  it('échoue si la réponse porte autre chose que le reçu', async () => {
    vi.mocked(opsGet).mockResolvedValue({ receipt: RECU, debug: {} });
    await expect(fetchReceipt(AXXX, 'sid', 'cid')).rejects.toThrow();
  });
});

describe('le PDF', () => {
  it('demande le document et nomme le fichier par la référence', async () => {
    const octets = new TextEncoder().encode('%PDF-1.4 …').buffer;
    vi.mocked(opsGetDocument).mockResolvedValue({
      contenu: octets, type: 'application/pdf',
    });
    const document = await fetchReceiptPdf(AXXX, 'sid', 'cid');
    expect(opsGetDocument).toHaveBeenCalledWith(
      `intakes/${AXXX}/receipt/pdf`, 'sid', 'cid');
    expect(document.nomFichier).toBe(`Recu_DallyTrading_${AXXX}.pdf`);
    expect(document.contenu.byteLength).toBeGreaterThan(0);
  });

  it('ne met jamais le nom du client dans le nom du fichier', () => {
    expect(nomFichierRecu(AXXX)).not.toContain('Aissatou');
    expect(nomFichierRecu(AXXX)).toBe(`Recu_DallyTrading_${AXXX}.pdf`);
  });

  it('neutralise une référence qui tenterait de sortir du dossier', () => {
    // Les tirets de tête, restes des séparateurs neutralisés, sont retirés.
    expect(nomFichierRecu('../../etc/passwd')).toBe(
      'Recu_DallyTrading_etc-passwd.pdf');
    expect(nomFichierRecu('..')).toBe('Recu_DallyTrading_recu.pdf');
    expect(nomFichierRecu('a"b')).not.toContain('"');
  });
});
