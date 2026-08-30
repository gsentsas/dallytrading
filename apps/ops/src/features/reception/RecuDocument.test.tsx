/**
 * Ce que le reçu affiche — et surtout ce qu'il n'affiche pas.
 *
 * Un zéro à la place d'un prix non arrêté, un solde calculé entre deux
 * monnaies, un identifiant technique laissé dans le document : trois erreurs
 * qu'un client emporterait chez lui.
 */

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { Recu } from '@/lib/ops/receipts';

const { RecuDocument } = await import('@/features/reception/RecuDocument');

const AXXX = 'AIR-DSS-CDG-TEST-001-A001';

const BASE: Recu = {
  document: { title: 'REÇU DE PRISE EN CHARGE', reference: AXXX,
              generated_at: '2026-08-30T09:15' },
  company: { name: 'DallyTrading', phone: '+221770000000',
             email: 'contact@example.test', address: 'Dakar', vat: '' },
  reference: AXXX,
  local_reference: 'DK-014',
  received_on: '2026-08-30',
  state: 'draft',
  transport_mode: 'air',
  transport_mode_label: 'Aérien',
  consolidation: { reference: 'AIR-DSS-CDG-TEST-001', origin: 'Dakar',
                   destination: 'Paris' },
  customer: { name: 'Aïssatou Ndèye Kandji', phone: '+221770000009',
              email: 'aissatou@example.test', address: 'Rue 10 Dakar' },
  articles: [{
    description: 'Épices, céréales & thé', goods_category: 'Alimentaire',
    quantity: 1, exact_weight_kg: 13.5, exact_weight_display: '13,5 kg',
    billable_weight_kg: 13.5,
    dimensions: '', customs_value_xof: 25000,
    tariff_family: 'Alimentaire standard',
    applied_unit_price_eur: 5, transport_amount_eur: 67.5,
    applied_unit_price_display: '5,00 €', transport_amount_display: '67,50 €',
  }],
  totals: {
    articles_count: 1, weight_kg: 13.5, weight_display: '13,5 kg',
    transport_amount_eur: 67.5, transport_amount_display: '67,50 €',
    currency_code: 'EUR',
    paid: [{ currency_code: 'XOF', amount: 100000, display: '100 000 FCFA' }],
    balance_eur: null, balance_display: '', balance_reason: 'currency_mismatch',
  },
  payments: [{
    date: '2026-08-30', amount: 100000, currency_code: 'XOF', method: 'Wave',
    collected_by: 'Gilles', wave_reference: 'TWXYZ12345',
    amount_display: '100 000 FCFA',
  }],
  operator: { name: 'Gilles Sène' },
  invoice_number: '',
};

const rendu = (recu: Recu) => renderToStaticMarkup(<RecuDocument recu={recu} />);

describe('le reçu affiché', () => {
  const html = rendu(BASE);

  it('se présente comme un reçu, jamais comme une facture', () => {
    expect(html).toContain('REÇU DE PRISE EN CHARGE');
    expect(html).toContain('Il ne constitue pas une facture');
  });

  it('nomme le client, le dossier et la route', () => {
    expect(html).toContain('Aïssatou Ndèye Kandji');
    expect(html).toContain(AXXX);
    expect(html).toContain('Dakar');
    expect(html).toContain('Paris');
    expect(html).toContain('Aérien');
  });

  it('affiche les montants et les poids tels que le serveur les a écrits', () => {
    expect(html).toContain('100 000 FCFA');
    expect(html).toContain('67,50 €');
    expect(html).toContain('13,5 kg');
    // Aucun nombre brut : le papier et l'écran écrivent les mêmes caractères.
    expect(html).not.toContain('13.5');
    expect(html).not.toContain('67.5');
  });

  it('nomme qui a réceptionné et qui a encaissé', () => {
    expect(html).toContain('Gilles Sène');
    expect(html).toContain('reçu par Gilles');
    expect(html).toContain('TWXYZ12345');
  });

  it('renvoie au détail plutôt que d’inventer un solde entre deux monnaies', () => {
    expect(html).toContain('Voir le détail des paiements');
    expect(html).toContain('ne sont pas dans la même monnaie');
    expect(html).not.toContain('-32');
  });

  it('ne laisse passer aucun identifiant technique', () => {
    for (const interdit of ['partner_id', 'shipment_id', 'invoice_id',
                            'sync_source_key', 'request_uuid']) {
      expect(html).not.toContain(interdit);
    }
  });
});

describe('les cas que le comptoir rencontre', () => {
  it('dit « à définir » plutôt que zéro quand le tarif n’est pas arrêté', () => {
    const html = rendu({
      ...BASE,
      articles: [{
        ...BASE.articles[0]!,
        applied_unit_price_eur: null, transport_amount_eur: null,
        applied_unit_price_display: '', transport_amount_display: '',
      }],
      totals: {
        ...BASE.totals, transport_amount_eur: null,
        transport_amount_display: '', balance_reason: 'pricing_incomplete',
      },
    });
    expect(html).toContain('Tarif à définir');
    expect(html).toContain('À définir');
    expect(html).toContain('n’est pas encore arrêté');
    expect(html).not.toContain('0,00 €');
  });

  it('dit clairement qu’aucun paiement n’a été reçu', () => {
    const html = rendu({
      ...BASE,
      payments: [],
      totals: { ...BASE.totals, paid: [], balance_eur: 67.5,
                balance_display: '67,50 €', balance_reason: null },
    });
    expect(html).toContain('Aucun paiement reçu à ce jour');
    expect(html).toContain('67,50 €');
  });

  it('garde les deux mouvements quand le client a payé deux fois', () => {
    const html = rendu({
      ...BASE,
      payments: [
        { ...BASE.payments[0]!, amount: 100000, amount_display: '100 000 FCFA',
          wave_reference: 'TW001' },
        { ...BASE.payments[0]!, amount: 50000, amount_display: '50 000 FCFA',
          wave_reference: 'TW002' },
      ],
      totals: {
        ...BASE.totals,
        paid: [{ currency_code: 'XOF', amount: 150000, display: '150 000 FCFA' }],
      },
    });
    expect(html).toContain('TW001');
    expect(html).toContain('TW002');
    expect(html).toContain('150 000 FCFA');
  });

  it('cite le numéro de facture quand il existe, sans devenir une facture', () => {
    const html = rendu({ ...BASE, invoice_number: 'INV/2026/00042' });
    expect(html).toContain('Facture associée : INV/2026/00042');
    expect(html).toContain('REÇU DE PRISE EN CHARGE');
    expect(html).toContain('Il ne constitue pas une facture');
  });
});
