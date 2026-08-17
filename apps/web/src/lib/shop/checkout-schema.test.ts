import { describe, expect, it } from 'vitest';

import {
  checkoutRequestSchema,
  guestCustomerSchema,
  shopOrderSchema,
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

const COMMANDE = {
  reference: 'S00042',
  status: 'draft' as const,
  deliveryMode: 'pickup' as const,
  deliveryModeLabel: 'Retrait sur place',
  currency: 'XOF',
  amountUntaxed: 300000,
  amountTax: 0,
  amountTotal: 300000,
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

  it('accepte une commande connectée sans bloc client', () => {
    expect(checkoutRequestSchema.parse({ deliveryMode: 'delivery_to_confirm' })).toEqual({
      deliveryMode: 'delivery_to_confirm',
    });
  });

  /**
   * Le cœur du contrat. Chaque nom listé ici décide d'un prix, d'une identité ou
   * d'un état de la commande. Un schéma permissif les ignorerait ; celui-ci les
   * refuse, parce qu'« ignorer » et « refuser » ne disent pas la même chose à qui
   * lit les journaux.
   */
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
    ['lignes fournies par le navigateur', { lines: [{ reference: 'x', quantity: 1 }] }],
    ['identifiant de panier', { cartId: '00000000-0000-4000-8000-000000000000' }],
  ])('refuse une demande portant %s', (_nom, extra) => {
    expect(() =>
      checkoutRequestSchema.parse({ deliveryMode: 'pickup', customer: INVITE, ...extra }),
    ).toThrow();
  });

  it('refuse un mode de remise inventé', () => {
    expect(() =>
      checkoutRequestSchema.parse({ deliveryMode: 'free_shipping', customer: INVITE }),
    ).toThrow();
  });

  it('refuse un mode de remise absent', () => {
    expect(() => checkoutRequestSchema.parse({ customer: INVITE })).toThrow();
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

  it('transforme un champ facultatif vide en absence, jamais en chaîne vide', () => {
    // Une chaîne vide écrirait `city = ''` dans Odoo, ce qui est différent de
    // « non renseigné » et rend le champ impossible à distinguer d'une saisie.
    const analyse = guestCustomerSchema.parse({
      name: 'X', email: 'x@essai.invalid', phone: '   ', city: '',
    });
    expect(analyse.phone).toBeUndefined();
    expect(analyse.city).toBeUndefined();
  });

  it('exige un nom non vide', () => {
    expect(() =>
      guestCustomerSchema.parse({ name: '   ', email: 'x@essai.invalid' }),
    ).toThrow();
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
    // Contrôle négatif : un contrôle trop strict refuserait des adresses réelles,
    // et le client n'aurait aucun moyen de commander.
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
    expect(() =>
      guestCustomerSchema.parse({ ...INVITE, vip: true }),
    ).toThrow();
  });

  it('borne les longueurs comme le contrôleur Odoo', () => {
    expect(() =>
      guestCustomerSchema.parse({ ...INVITE, name: 'a'.repeat(129) }),
    ).toThrow();
    expect(
      guestCustomerSchema.parse({ ...INVITE, name: 'a'.repeat(128) }).name,
    ).toHaveLength(128);
    expect(() =>
      guestCustomerSchema.parse({ ...INVITE, street: 'a'.repeat(201) }),
    ).toThrow();
  });

  it('met le code pays en majuscules et refuse les autres formes', () => {
    expect(guestCustomerSchema.parse({ ...INVITE, country_code: 'sn' }).country_code)
      .toBe('SN');
    expect(() =>
      guestCustomerSchema.parse({ ...INVITE, country_code: 'SEN' }),
    ).toThrow();
    expect(
      guestCustomerSchema.parse({ ...INVITE, country_code: '' }).country_code,
    ).toBeUndefined();
  });
});

describe('commande rendue', () => {
  it('accepte la projection mesurée sur l’instance', () => {
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

  it('refuse un état inconnu', () => {
    // Énumération fermée sur les quatre états de `sale.order`. Au MVP seul
    // `draft` sort d'ici ; fermer l'énumération fait échouer le contrat le jour
    // où quelque chose commencerait à confirmer, plutôt qu'afficher un état
    // inconnu au client.
    expect(() => shopOrderSchema.parse({ ...COMMANDE, status: 'done' })).toThrow();
  });

  it('accepte les quatre états réels de sale.order', () => {
    for (const status of ['draft', 'sent', 'sale', 'cancel'] as const) {
      expect(shopOrderSchema.parse({ ...COMMANDE, status }).status).toBe(status);
    }
  });

  it('refuse une ligne portant une clé de trop', () => {
    expect(() =>
      shopOrderSchema.parse({
        ...COMMANDE,
        lines: [{ ...COMMANDE.lines[0], price_unit: 1 }],
      }),
    ).toThrow();
  });

  it('exige le drapeau de rejeu', () => {
    // Sans lui le BFF ne saurait pas s'il vient de créer une commande ou d'en
    // retrouver une, et il ferait tourner l'identifiant de panier dans les deux
    // cas — ce qui est correct, mais il faut pouvoir le dire.
    const { replayed: _ignore, ...sans } = COMMANDE;
    expect(() => shopOrderSchema.parse(sans)).toThrow();
  });
});
