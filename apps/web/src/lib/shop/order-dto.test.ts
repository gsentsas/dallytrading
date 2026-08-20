import { describe, expect, it } from 'vitest';

import {
  shopOrderDetailEnvelopeSchema,
  shopOrderDetailSchema,
  shopOrderLineSchema,
  shopOrderListItemSchema,
  shopOrderListSchema,
} from './order-dto';

const LIGNE = {
  productName: 'Article portail',
  quantity: 2,
  unitPrice: 150000,
  subtotal: 300000,
};

const ELEMENT = {
  reference: 'S00042',
  date: '2026-08-17T09:15:00',
  stateLabel: 'Commande reçue — en attente de validation',
  currency: 'XOF',
  amountUntaxed: 300000,
  amountTax: 0,
  amountTotal: 300000,
  deliveryMode: 'pickup' as const,
  deliveryModeLabel: 'Retrait sur place',
  itemCount: 2,
};

const DETAIL = {
  reference: 'S00042',
  date: '2026-08-17T09:15:00',
  state: 'received' as const,
  stateLabel: 'Commande reçue — en attente de validation',
  deliveryMode: 'pickup' as const,
  deliveryModeLabel: 'Retrait sur place',
  currency: 'XOF',
  amountUntaxed: 300000,
  amountTax: 0,
  amountTotal: 300000,
  lines: [LIGNE],
  deliveryAddress: {
    name: 'Client Portail A',
    street: '1 rue de Test',
    city: 'Dakar',
    zip: '11000',
    country: 'Sénégal',
  },
};

describe('ligne de commande', () => {
  it('accepte la forme mesurée', () => {
    expect(shopOrderLineSchema.parse(LIGNE)).toEqual(LIGNE);
  });

  it('accepte une quantité flottante', () => {
    expect(shopOrderLineSchema.parse({ ...LIGNE, quantity: 2.5 }).quantity).toBe(2.5);
  });

  it.each([
    ['coût', { cost: 12000 }],
    ['coût interne Odoo', { purchase_price: 12000 }],
    ['marge', { margin: 0.42 }],
    ['marge en pourcentage', { margin_percent: 42 }],
    ['fournisseur', { supplier: 'FOURNISSEUR' }],
    ['identifiant technique', { id: 4711 }],
    ['identifiant de produit', { product_id: 42 }],
    ['identifiant de commande', { order_id: 7 }],
    ['remise', { discount: 90 }],
    ['taxes', { tax_ids: [] }],
    ['note interne', { internalNote: 'secret' }],
  ])('refuse une ligne portant %s', (_nom, extra) => {
    expect(() => shopOrderLineSchema.parse({ ...LIGNE, ...extra })).toThrow();
  });
});

describe('élément de liste', () => {
  it('accepte la forme mesurée', () => {
    expect(shopOrderListItemSchema.parse(ELEMENT)).toEqual(ELEMENT);
  });

  it('accepte une date et un mode de remise nuls', () => {
    const analyse = shopOrderListItemSchema.parse({
      ...ELEMENT, date: null, deliveryMode: null,
    });
    expect(analyse.date).toBeNull();
    expect(analyse.deliveryMode).toBeNull();
  });

  it('exige un libellé d’état non vide', () => {
    expect(() => shopOrderListItemSchema.parse({ ...ELEMENT, stateLabel: '' })).toThrow();
  });

  it('n’expose pas l’état brut dans la liste', () => {
    expect(() => shopOrderListItemSchema.parse({ ...ELEMENT, state: 'received' })).toThrow();
  });

  it.each([
    ['coût', { cost: 1 }],
    ['marge', { margin: 1 }],
    ['prix d’achat', { purchase_price: 1 }],
    ['fournisseur', { supplier: 'X' }],
    ['identifiant technique', { id: 42 }],
    ['identifiant de partenaire', { partner_id: 3 }],
    ['partenaire commercial', { commercial_partner_id: 3 }],
    ['identifiant de panier', { cartId: '00000000-0000-4000-8000-000000000000' }],
  ])('refuse un élément portant %s', (_nom, extra) => {
    expect(() => shopOrderListItemSchema.parse({ ...ELEMENT, ...extra })).toThrow();
  });

  it('accepte une liste vide', () => {
    expect(shopOrderListSchema.parse({ orders: [] })).toEqual({ orders: [] });
  });

  it('refuse une clé de trop au niveau de la liste', () => {
    expect(() => shopOrderListSchema.parse({ orders: [], total: 0 })).toThrow();
  });
});

describe('détail de commande', () => {
  it('accepte la forme mesurée', () => {
    expect(shopOrderDetailSchema.parse(DETAIL)).toEqual(DETAIL);
  });

  it('accepte exactement les quatre états du workflow boutique', () => {
    for (const state of ['received', 'validated', 'rejected', 'cancelled'] as const) {
      expect(shopOrderDetailSchema.parse({ ...DETAIL, state }).state).toBe(state);
    }
  });

  it('refuse les états natifs de sale.order et les états inconnus', () => {
    for (const state of ['draft', 'sent', 'sale', 'cancel', 'done']) {
      expect(() => shopOrderDetailSchema.parse({ ...DETAIL, state })).toThrow();
    }
  });

  it.each([
    ['coût', { cost: 1 }],
    ['marge', { margin: 1 }],
    ['prix d’achat', { purchase_price: 1 }],
    ['fournisseur', { supplier: 'X' }],
    ['note interne', { note: 'CANARY_SHOP_INTERNAL_NOTE' }],
    ['identifiant technique', { id: 42 }],
    ['identifiant de partenaire', { partner_id: 3 }],
    ['vendeur', { user_id: 2 }],
    ['position fiscale', { fiscal_position_id: 1 }],
    ['conditions de paiement', { payment_term_id: 1 }],
    ['identifiant de panier', { dally_shop_cart_uuid: 'x' }],
  ])('refuse un détail portant %s', (_nom, extra) => {
    expect(() => shopOrderDetailSchema.parse({ ...DETAIL, ...extra })).toThrow();
  });

  it('refuse une adresse portant une clé de trop', () => {
    expect(() =>
      shopOrderDetailSchema.parse({
        ...DETAIL,
        deliveryAddress: { ...DETAIL.deliveryAddress, partner_id: 3 },
      }),
    ).toThrow();
  });

  it('refuse une ligne portant une clé de trop, au travers du détail', () => {
    expect(() =>
      shopOrderDetailSchema.parse({
        ...DETAIL,
        lines: [{ ...LIGNE, purchase_price: 12000 }],
      }),
    ).toThrow();
  });

  it('l’enveloppe n’accepte que la clé « order »', () => {
    expect(shopOrderDetailEnvelopeSchema.parse({ order: DETAIL })).toEqual({
      order: DETAIL,
    });
    expect(() =>
      shopOrderDetailEnvelopeSchema.parse({ order: DETAIL, meta: {} }),
    ).toThrow();
  });
});

describe('correspondance des états, vue du contrat', () => {
  it('« Commande reçue » est un libellé accepté', () => {
    const analyse = shopOrderDetailSchema.parse({
      ...DETAIL,
      state: 'received',
      stateLabel: 'Commande reçue — en attente de validation',
    });
    expect(analyse.stateLabel).toContain('Commande reçue');
    expect(analyse.stateLabel.toLowerCase()).not.toContain('brouillon');
  });

  it('le motif client peut être porté par le libellé sans nouvelle clé', () => {
    const analyse = shopOrderDetailSchema.parse({
      ...DETAIL,
      state: 'rejected',
      stateLabel: 'Commande refusée — Référence momentanément indisponible',
    });
    expect(analyse.stateLabel).toContain('Référence momentanément indisponible');
    expect(() =>
      shopOrderDetailSchema.parse({ ...analyse, stateReason: 'clé non contractuelle' }),
    ).toThrow();
  });

  it('le libellé traverse tel quel, sans être recalculé ici', () => {
    const inattendu = 'Un libellé que le frontend ne connaît pas';
    expect(
      shopOrderDetailSchema.parse({ ...DETAIL, stateLabel: inattendu }).stateLabel,
    ).toBe(inattendu);
  });
});
