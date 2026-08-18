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
  imageVersion: null,
  category: { reference: 'groupes-electrogenes', name: 'Groupes électrogènes' },
} as const;

const DETAIL = {
  ...PRODUIT,
  description: 'Description commerciale.',
  unit: 'Units',
  gallery: [{ reference: 'bbbb000000000002', sequence: 10 }],
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

describe('empreinte de l’image', () => {
  it('accepte une empreinte', () => {
    const produit = { ...PRODUIT, imageVersion: 'a1b2c3d4e5f60718' };
    expect(shopProductSchema.parse(produit).imageVersion).toBe('a1b2c3d4e5f60718');
  });

  it('accepte l’absence d’image', () => {
    expect(shopProductSchema.parse({ ...PRODUIT, imageVersion: null }).imageVersion)
      .toBeNull();
  });

  it('tolère un Odoo qui ne l’envoie pas encore', () => {
    /*
     * La propriété qui rend l'ordre de déploiement libre.
     *
     * Le champ est ajouté des deux côtés. S'il était requis ici, ce frontend
     * exigerait un Odoo déjà monté de version, et la boutique tomberait entre
     * les deux opérations — l'incident décrit en tête de `dto.ts`, dans l'autre
     * sens. Avec un défaut, les deux ordres fonctionnent.
     */
    const { imageVersion: _absent, ...sansChamp } = PRODUIT;
    expect(shopProductSchema.parse(sansChamp).imageVersion).toBeNull();
  });

  it('refuse une empreinte vide', () => {
    // Une chaîne vide produirait une URL sans jeton, donc un cache court sur
    // une image qui n'existe pas. `null` est le seul « pas d'image » accepté.
    expect(() =>
      shopProductSchema.parse({ ...PRODUIT, imageVersion: '' }),
    ).toThrow();
  });

  it('refuse des octets à la place de l’empreinte', () => {
    // Le contrat interdit structurellement le base64 massif : le champ est une
    // chaîne, mais un objet ou un tableau d'octets est rejeté, et rien dans le
    // schéma n'offre d'endroit où poser une image.
    expect(() =>
      shopProductSchema.parse({ ...PRODUIT, imageVersion: { data: 'iVBORw0KGgo' } }),
    ).toThrow();
  });

  it('la fiche et la tuile portent le même champ', () => {
    // Un mécanisme unique : si la fiche avait son propre champ image, les deux
    // divergeraient et le navigateur téléchargerait deux fois la même image.
    const tuile = shopProductSchema.parse({ ...PRODUIT, imageVersion: 'aaaa1111' });
    const fiche = shopProductDetailSchema.parse({ ...DETAIL, imageVersion: 'aaaa1111' });
    expect(fiche.imageVersion).toBe(tuile.imageVersion);
  });
});

describe('contrat de la galerie', () => {
  it('accepte une galerie de plusieurs photos', () => {
    const fiche = shopProductDetailSchema.parse({
      ...DETAIL,
      gallery: [
        { reference: 'a'.repeat(16), sequence: 10 },
        { reference: 'b'.repeat(16), sequence: 20 },
      ],
    });
    expect(fiche.gallery).toHaveLength(2);
  });

  it('accepte une fiche sans galerie', () => {
    expect(shopProductDetailSchema.parse({ ...DETAIL, gallery: [] }).gallery).toEqual([]);
  });

  it('tolère un Odoo qui n’envoie pas encore le champ', () => {
    // Même raison qu'`imageVersion` : l'ordre de déploiement doit rester libre.
    const { gallery: _absente, ...sansChamp } = DETAIL;
    expect(shopProductDetailSchema.parse(sansChamp).gallery).toEqual([]);
  });

  it('refuse la galerie sur le schéma de liste', () => {
    // La propriété structurelle : une tuile de catalogue ne peut pas porter
    // trente jetons, parce que le contrat n'a pas d'endroit où les mettre.
    expect(() =>
      shopProductSchema.parse({ ...PRODUIT, gallery: [] }),
    ).toThrow();
  });

  it('refuse un identifiant de base dans une photo', () => {
    for (const extra of [{ id: 42 }, { productImageId: 42 }, { product_tmpl_id: 384 }]) {
      expect(() =>
        shopProductDetailSchema.parse({
          ...DETAIL,
          gallery: [{ reference: 'a'.repeat(16), sequence: 10, ...extra }],
        }),
      ).toThrow();
    }
  });

  it('refuse des octets à la place du jeton', () => {
    expect(() =>
      shopProductDetailSchema.parse({
        ...DETAIL,
        gallery: [{ reference: { data: 'iVBORw0KGgo' }, sequence: 10 }],
      }),
    ).toThrow();
    expect(() =>
      shopProductDetailSchema.parse({
        ...DETAIL,
        gallery: [{ reference: '', sequence: 10 }],
      }),
    ).toThrow();
  });

  it('exige une séquence entière', () => {
    expect(() =>
      shopProductDetailSchema.parse({
        ...DETAIL,
        gallery: [{ reference: 'a'.repeat(16), sequence: 1.5 }],
      }),
    ).toThrow();
  });
});
