import { describe, expect, it } from 'vitest';

import {
  checkoutRequestSchema,
  guestCustomerSchema,
  shopOrderSchema,
  shopWorkflowStateSchema,
} from './checkout-schema';

const INVITE = {
  name: 'Invité Test',
  email: 'invite@essai.invalid',
  phone: '+221 77 000 00 00',
  street: '1 rue de Test',
  city: 'Dakar',
  zip: '11000',
  country_code: 'SN',
};

const DELIVERY = {
  method: {
    code: 'pickup',
    name: 'Retrait sur place',
    kind: 'pickup' as const,
    requiresAddress: false,
  },
  fee: {
    status: 'free' as const,
    amount: 0,
    currency: 'XOF',
  },
  shippingAddress: null,
  fulfillment: {
    state: 'pending' as const,
    label: 'En attente de préparation',
  },
};

const COMMANDE = {
  reference: 'S00042',
  status: 'received' as const,
  deliveryMode: 'pickup',
  deliveryModeLabel: 'Retrait sur place',
  currency: 'XOF',
  amountUntaxed: 300000,
  amountTax: 0,
  amountTotal: 300000,
  delivery: DELIVERY,
  grandTotal: 300000,
  lines: [
    {
      reference: 'filtre-a-huile',
      name: 'Filtre à huile',
      quantity: 2,
      unitPrice: 150000,
      subtotal: 300000,
    },
  ],
  replayed: false,
};

describe('demande de commande', () => {
  it('accepte une commande invité complète', () => {
    const analyse = checkoutRequestSchema.parse({
      deliveryMode: 'pickup',
      customer: INVITE,
    });
    expect(analyse.customer?.email).toBe('invite@essai.invalid');
  });

  it('accepte une méthode configurable bien formée', () => {
    expect(checkoutRequestSchema.parse({ deliveryMode: 'dakar-express' }).deliveryMode)
      .toBe('dakar-express');
  });

  it('accepte une adresse de livraison distincte strictement bornée', () => {
    const analyse = checkoutRequestSchema.parse({
      deliveryMode: 'delivery_to_confirm',
      shipping: {
        name: 'Dépôt Dakar',
        street: '10 avenue de la République',
        city: 'Dakar',
        country_code: 'sn',
      },
    });
    expect(analyse.shipping?.country_code).toBe('SN');
  });

  it.each([
    ['price_unit', { price_unit: 1 }],
    ['prix', { price: 1 }],
    ['remise', { discount: 90 }],
    ['tax_id', { tax_id: 1 }],
    ['tax_ids', { tax_ids: [] }],
    ['pricelist_id', { pricelist_id: 1 }],
    ['partner_id', { partner_id: 3 }],
    ['company_id', { company_id: 1 }],
    ['state', { state: 'sale' }],
    ['order_id', { order_id: 7 }],
    ['amount_total', { amount_total: 1 }],
    ['frais de livraison', { deliveryFee: 1 }],
    ['lignes fournies par le navigateur', { lines: [{ reference: 'x', quantity: 1 }] }],
    ['identifiant de panier', { cartId: '00000000-0000-4000-8000-000000000000' }],
  ])('refuse une demande portant %s', (_nom, extra) => {
    expect(() =>
      checkoutRequestSchema.parse({ deliveryMode: 'pickup', customer: INVITE, ...extra }),
    ).toThrow();
  });

  it.each(['Libre Livraison', 'UPPERCASE', '../pickup', 'a/b', '', 'méthode'])
    ('refuse un code de méthode mal formé : %s', (deliveryMode) => {
      expect(() => checkoutRequestSchema.parse({ deliveryMode })).toThrow();
    });

  it('refuse un mode de remise absent', () => {
    expect(() => checkoutRequestSchema.parse({ customer: INVITE })).toThrow();
  });

  it('refuse un prix glissé dans adresse de livraison', () => {
    expect(() => checkoutRequestSchema.parse({
      deliveryMode: 'delivery_to_confirm',
      shipping: { street: 'X', city: 'Dakar', fee: 1 },
    })).toThrow();
  });
});

describe('identité invité', () => {
  it('coupe les espaces de bord', () => {
    const analyse = guestCustomerSchema.parse({
      ...INVITE,
      name: '  Invité Test  ',
      email: '  invite@essai.invalid  ',
    });
    expect(analyse.name).toBe('Invité Test');
    expect(analyse.email).toBe('invite@essai.invalid');
  });

  it('transforme un champ facultatif vide en absence', () => {
    const analyse = guestCustomerSchema.parse({
      name: 'X', email: 'x@essai.invalid', phone: '   ', city: '',
    });
    expect(analyse.phone).toBeUndefined();
    expect(analyse.city).toBeUndefined();
  });

  it('exige un nom non vide', () => {
    expect(() => guestCustomerSchema.parse({ name: '   ', email: 'x@essai.invalid' })).toThrow();
  });

  it.each([
    'pas-une-adresse',
    'sans@point',
    '@commence-par-arobase.invalid',
    'espace dans@adresse.invalid',
    'deux@@arobases.invalid',
    'virgule,dedans@essai.invalid',
  ])('refuse l’adresse « %s »', (email) => {
    expect(() => guestCustomerSchema.parse({ name: 'X', email })).toThrow();
  });

  it('accepte les formes valides inhabituelles', () => {
    for (const email of [
      'a+etiquette@essai.invalid',
      'prenom.nom@sous.domaine.invalid',
      'chiffres123@essai.invalid',
      "apostrophe'ok@essai.invalid",
    ]) {
      expect(guestCustomerSchema.parse({ name: 'X', email }).email).toBe(email);
    }
  });

  it('refuse un champ client inconnu', () => {
    expect(() => guestCustomerSchema.parse({ ...INVITE, vip: true })).toThrow();
  });

  it('borne les longueurs comme le contrôleur Odoo', () => {
    expect(() => guestCustomerSchema.parse({ ...INVITE, name: 'a'.repeat(129) })).toThrow();
    expect(guestCustomerSchema.parse({ ...INVITE, name: 'a'.repeat(128) }).name).toHaveLength(128);
    expect(() => guestCustomerSchema.parse({ ...INVITE, street: 'a'.repeat(201) })).toThrow();
  });

  it('met le code pays en majuscules et refuse les autres formes', () => {
    expect(guestCustomerSchema.parse({ ...INVITE, country_code: 'sn' }).country_code).toBe('SN');
    expect(() => guestCustomerSchema.parse({ ...INVITE, country_code: 'SEN' })).toThrow();
    expect(guestCustomerSchema.parse({ ...INVITE, country_code: '' }).country_code).toBeUndefined();
  });
});

describe('commande rendue', () => {
  it('accepte la projection Lot C mesurée au checkout', () => {
    expect(shopOrderSchema.parse(COMMANDE)).toEqual(COMMANDE);
  });

  it.each([
    ['coût interne', { cost: 12000 }],
    ['marge', { margin: 0.4 }],
    ['identifiant de partenaire', { partner_id: 3 }],
    ['identifiant de base', { id: 42 }],
    ['identifiant de panier', { cartId: '00000000-0000-4000-8000-000000000000' }],
    ['note interne', { internalNote: 'secret' }],
  ])('refuse une commande portant %s', (_nom, extra) => {
    expect(() => shopOrderSchema.parse({ ...COMMANDE, ...extra })).toThrow();
  });

  it('refuse un état commercial inconnu', () => {
    expect(() => shopOrderSchema.parse({ ...COMMANDE, status: 'done' })).toThrow();
  });

  it('accepte exactement les quatre états publics du workflow boutique', () => {
    for (const status of ['received', 'validated', 'rejected', 'cancelled'] as const) {
      expect(shopWorkflowStateSchema.parse(status)).toBe(status);
      expect(shopOrderSchema.parse({ ...COMMANDE, status }).status).toBe(status);
    }
  });

  it('refuse les états natifs de sale.order dans le contrat public', () => {
    for (const status of ['draft', 'sent', 'sale', 'cancel']) {
      expect(() => shopOrderSchema.parse({ ...COMMANDE, status })).toThrow();
    }
  });

  it('une livraison cotée peut rendre un total global inconnu', () => {
    const commande = shopOrderSchema.parse({
      ...COMMANDE,
      deliveryMode: 'delivery_to_confirm',
      deliveryModeLabel: 'Livraison',
      delivery: {
        method: {
          code: 'delivery_to_confirm', name: 'Livraison', kind: 'delivery', requiresAddress: true,
        },
        fee: { status: 'pending_quote', amount: null, currency: 'XOF' },
        shippingAddress: {
          name: 'Client', phone: '', street: 'Rue 1', street2: '', city: 'Dakar', zip: '', countryCode: 'SN',
        },
        fulfillment: { state: 'pending', label: 'En attente de préparation' },
      },
      grandTotal: null,
    });
    expect(commande.delivery.fee.amount).toBeNull();
    expect(commande.grandTotal).toBeNull();
  });

  it('refuse un coût ou identifiant technique dans la projection livraison', () => {
    expect(() => shopOrderSchema.parse({
      ...COMMANDE,
      delivery: {
        ...DELIVERY,
        method: { ...DELIVERY.method, id: 9 },
      },
    })).toThrow();
  });

  it('refuse une ligne portant une clé de trop', () => {
    expect(() => shopOrderSchema.parse({
      ...COMMANDE,
      lines: [{ ...COMMANDE.lines[0], price_unit: 1 }],
    })).toThrow();
  });

  it('exige le drapeau de rejeu', () => {
    const { replayed: _ignore, ...sans } = COMMANDE;
    expect(() => shopOrderSchema.parse(sans)).toThrow();
  });
});
