import { describe, expect, it } from 'vitest';

import {
  cartViewSchema,
  resolvedCartSchema,
  shopCatalogueSchema,
  shopProductDetailSchema,
  shopProductSchema,
} from './dto';

/** Un produit valide, dans la forme exacte que la projection Odoo produit. */
const PRODUIT = {
  reference: 'groupe-electrogene-5kva',
  name: 'Groupe électrogène 5 kVA',
  summary: 'Groupe électrogène monophasé.',
  price: 150000,
  currency: 'XOF',
  stockPolicy: 'on_order',
  stockPolicyLabel: 'Sur commande',
  availability: 'on_order',
  category: { reference: 'groupes-electrogenes', name: 'Groupes électrogènes' },
} as const;

const DETAIL = {
  ...PRODUIT,
  description: 'Description commerciale.',
  unit: 'Units',
} as const;

describe('contrat produit', () => {
  it('accepte la projection mesurée sur l’instance', () => {
    expect(shopProductSchema.parse(PRODUIT)).toEqual(PRODUIT);
  });

  it('accepte un résumé et une catégorie nuls', () => {
    // Mesuré : la projection envoie `null`, jamais une clé absente. Un
    // `.optional()` sans `.nullable()` échouerait sur la donnée réelle.
    expect(
      shopProductSchema.parse({ ...PRODUIT, summary: null, category: null }),
    ).toMatchObject({ summary: null, category: null });
  });

  /**
   * Le cœur du contrat. Chaque nom listé ici est un champ qu'un `product.template`
   * porte réellement en base, et dont la présence dans une réponse publique serait
   * une fuite : le coût d'achat donne la marge, donc la limite de négociation.
   */
  it.each([
    ['standard_price', { standard_price: 424242.42 }],
    ['cout interne', { cost: 12000 }],
    ['marge', { margin: 0.42 }],
    ['prix de liste', { list_price: 999999 }],
    ['note interne', { description: 'note interne', internalNote: 'secret' }],
    ['fournisseur', { supplier: 'FOURNISSEUR' }],
    ['identifiant de base', { id: 1875 }],
    ['quantité en stock', { qtyAvailable: 12 }],
    ['identifiant de modèle', { productTmplId: 1875 }],
  ])('refuse une réponse portant %s', (_nom, extra) => {
    expect(() => shopProductSchema.parse({ ...PRODUIT, ...extra })).toThrow();
  });

  it('refuse une politique de stock inconnue', () => {
    // Énumération fermée : une valeur inattendue doit faire échouer le contrat
    // plutôt que produire une étiquette vide sur la fiche.
    expect(() =>
      shopProductSchema.parse({ ...PRODUIT, stockPolicy: 'reserved' }),
    ).toThrow();
  });

  it('refuse une disponibilité inconnue', () => {
    expect(() =>
      shopProductSchema.parse({ ...PRODUIT, availability: 'maybe' }),
    ).toThrow();
  });

  it('refuse un prix négatif', () => {
    expect(() => shopProductSchema.parse({ ...PRODUIT, price: -1 })).toThrow();
  });

  it('refuse une catégorie portant une clé de trop', () => {
    expect(() =>
      shopProductSchema.parse({
        ...PRODUIT,
        category: { reference: 'a', name: 'A', id: 3 },
      }),
    ).toThrow();
  });
});

describe('contrat de la fiche', () => {
  it('accepte les deux clés supplémentaires', () => {
    expect(shopProductDetailSchema.parse(DETAIL)).toEqual(DETAIL);
  });

  it('refuse la fiche sur le schéma de liste, et réciproquement', () => {
    // Les deux schémas ne sont pas interchangeables : c'est ce qui garantit que
    // la liste ne se met pas à transporter une description complète.
    expect(() => shopProductSchema.parse(DETAIL)).toThrow();
    expect(() => shopProductDetailSchema.parse(PRODUIT)).toThrow();
  });
});

describe('contrat du catalogue', () => {
  it('accepte une réponse complète', () => {
    const catalogue = {
      products: [PRODUIT],
      categories: [
        { reference: 'groupes-electrogenes', name: 'Groupes électrogènes', productCount: 2 },
      ],
    };
    expect(shopCatalogueSchema.parse(catalogue)).toEqual(catalogue);
  });

  it('accepte un catalogue vide', () => {
    // Un catalogue vide est un état normal — publication fermée par défaut — et
    // non une erreur à traiter.
    expect(shopCatalogueSchema.parse({ products: [], categories: [] })).toEqual({
      products: [],
      categories: [],
    });
  });

  it('refuse une clé supplémentaire au niveau du catalogue', () => {
    expect(() =>
      shopCatalogueSchema.parse({ products: [], categories: [], pricelistId: 1319 }),
    ).toThrow();
  });
});

describe('contrat du panier résolu', () => {
  const LIGNE = { ...PRODUIT, quantity: 2, subtotal: 300000 };
  const PANIER = {
    lines: [LIGNE],
    removed: ['produit-dépublié'],
    itemCount: 2,
    subtotal: 300000,
    currency: 'XOF',
    total: 300000,
  };

  it('accepte un panier résolu', () => {
    expect(resolvedCartSchema.parse(PANIER)).toEqual(PANIER);
  });

  it('refuse une quantité nulle sur une ligne résolue', () => {
    // Une ligne à quantité zéro ne devrait jamais revenir d'Odoo : elle serait
    // retirée. La refuser rend le désaccord bruyant.
    expect(() =>
      resolvedCartSchema.parse({ ...PANIER, lines: [{ ...LIGNE, quantity: 0 }] }),
    ).toThrow();
  });

  /**
   * `cartId` ne doit pas franchir la frontière : il sert de clé d'idempotence à la
   * commande, et l'exposer inviterait à le renvoyer, donc à le choisir.
   */
  it('refuse un panier portant l’identifiant de panier', () => {
    expect(() =>
      resolvedCartSchema.parse({ ...PANIER, cartId: '00000000-0000-4000-8000-000000000000' }),
    ).toThrow();
    expect(() =>
      cartViewSchema.parse({
        ...PANIER,
        lineCount: 1,
        maxLines: 20,
        cartId: '00000000-0000-4000-8000-000000000000',
      }),
    ).toThrow();
  });

  it('la vue ajoute exactement deux clés', () => {
    const vue = { ...PANIER, lineCount: 1, maxLines: 20 };
    expect(cartViewSchema.parse(vue)).toEqual(vue);
    // Sans elles, la vue est incomplète : la page a besoin de connaître le
    // plafond pour le dire au client avant qu'il l'atteigne.
    expect(() => cartViewSchema.parse(PANIER)).toThrow();
  });
});
