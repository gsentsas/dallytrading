import { describe, expect, it } from 'vitest';

import {
  CART_COOKIE,
  CART_MAX_AGE_SECONDS,
  CartError,
  MAX_CART_LINES,
  MAX_LINE_QUANTITY,
  cartCookieOptions,
  clearLines,
  isValidQuantity,
  isValidReference,
  newCart,
  sealCart,
  setLine,
  unsealCart,
  type Cart,
} from './cart';

const SECRET = 'shop-cart-secret-for-unit-tests-only-0123456789abcdef';
const AUTRE_SECRET = 'a-different-shop-secret-of-sufficient-length-9876543210';

/** Le secret du portail, pour prouver qu'il ne déverrouille pas le panier. */
const SECRET_PORTAIL = 'test-secret-for-unit-tests-only-not-a-real-value-0123456789';

function panier(lignes: Array<{ reference: string; quantity: number }> = []): Cart {
  return { ...newCart(), lines: lignes };
}

describe('scellement du panier', () => {
  it('fait l’aller-retour sans perte', () => {
    const original = panier([{ reference: 'groupe-electrogene-5kva', quantity: 2 }]);
    expect(unsealCart(sealCart(original, SECRET), SECRET)).toEqual(original);
  });

  it('produit un scellé différent à chaque appel (IV aléatoire)', () => {
    const original = panier([{ reference: 'filtre-a-huile', quantity: 1 }]);
    expect(sealCart(original, SECRET)).not.toBe(sealCart(original, SECRET));
  });

  it('n’expose pas son contenu en clair', () => {
    const scelle = sealCart(panier([{ reference: 'onduleur-3kva', quantity: 3 }]), SECRET);
    expect(scelle).not.toContain('onduleur-3kva');
    expect(scelle).not.toContain('quantity');
    expect(Buffer.from(scelle).toString('utf8')).not.toContain('cartId');
  });

  it('refuse un panier scellé avec un autre secret', () => {
    const scelle = sealCart(panier(), AUTRE_SECRET);
    expect(() => unsealCart(scelle, SECRET)).toThrow(CartError);
  });

  /**
   * Le point de la décision « secret distinct » : le secret du portail ne doit
   * pas ouvrir un panier, et réciproquement. Sans ce test, les deux pourraient
   * dériver vers la même valeur sans que rien ne le signale.
   */
  it('n’est pas ouvrable avec le secret du portail', () => {
    const scelle = sealCart(panier([{ reference: 'filtre-a-huile', quantity: 1 }]), SECRET);
    expect(() => unsealCart(scelle, SECRET_PORTAIL)).toThrow(CartError);
  });

  /**
   * Mutation du **premier** caractère du tag, jamais du dernier.
   *
   * Le tag GCM fait 16 octets, soit 22 caractères base64url dont le dernier ne
   * porte que deux bits utiles : une substitution sur quatre y redonne le même
   * tag, le déchiffrement réussit, et le test passe une fois sur quatre. Ce
   * scintillement a été diagnostiqué sur le cookie du portail ; il ne sera pas
   * reproduit ici.
   */
  it('refuse un cookie dont le tag a été altéré', () => {
    const scelle = sealCart(panier([{ reference: 'filtre-a-huile', quantity: 1 }]), SECRET);
    const morceaux = scelle.split('.');
    const tag = morceaux[3] as string;
    const premier = tag[0] === 'A' ? 'B' : 'A';
    morceaux[3] = premier + tag.slice(1);
    expect(() => unsealCart(morceaux.join('.'), SECRET)).toThrow(CartError);
  });

  it('refuse une charge altérée', () => {
    const scelle = sealCart(panier([{ reference: 'filtre-a-huile', quantity: 1 }]), SECRET);
    const morceaux = scelle.split('.');
    const data = morceaux[2] as string;
    morceaux[2] = (data[0] === 'A' ? 'B' : 'A') + data.slice(1);
    expect(() => unsealCart(morceaux.join('.'), SECRET)).toThrow(CartError);
  });

  it.each([
    ['vide', ''],
    ['sans séparateur', 'nimportequoi'],
    ['version inconnue', 'v2.AAAA.BBBB.CCCC'],
    ['trois morceaux', 'v1.AAAA.BBBB'],
    ['cinq morceaux', 'v1.AAAA.BBBB.CCCC.DDDD'],
    ['base64 invalide', 'v1.!!!!.!!!!.!!!!'],
  ])('refuse un cookie %s', (_nom, valeur) => {
    expect(() => unsealCart(valeur, SECRET)).toThrow(CartError);
  });
});

describe('le panier ne transporte aucun prix', () => {
  /**
   * Le contrôle est sur la **structure du paquet**, pas sur ce que l'appelant a
   * bien voulu y mettre. Un prix authentiquement scellé serait authentiquement
   * périmé, et le refuser à l'ouverture est la seule façon d'empêcher qu'un futur
   * appelant s'en serve.
   */
  it('refuse une ligne portant une clé supplémentaire', () => {
    const contrebande = {
      ...newCart(),
      lines: [{ reference: 'filtre-a-huile', quantity: 1, price: 1 }],
    };
    const scelle = sealCart(contrebande as unknown as Cart, SECRET);
    expect(() => unsealCart(scelle, SECRET)).toThrow(CartError);
  });

  it('refuse une ligne à laquelle il manque une clé', () => {
    const tronque = { ...newCart(), lines: [{ reference: 'filtre-a-huile' }] };
    const scelle = sealCart(tronque as unknown as Cart, SECRET);
    expect(() => unsealCart(scelle, SECRET)).toThrow(CartError);
  });

  it('le scellé d’un panier de deux lignes ne contient aucun chiffre de prix', () => {
    const scelle = sealCart(
      panier([
        { reference: 'groupe-electrogene-5kva', quantity: 2 },
        { reference: 'onduleur-3kva', quantity: 1 },
      ]),
      SECRET,
    );
    const ouvert = unsealCart(scelle, SECRET);
    for (const ligne of ouvert.lines) {
      expect(Object.keys(ligne).sort()).toEqual(['quantity', 'reference']);
    }
  });
});

describe('bornes revérifiées à l’ouverture', () => {
  /**
   * Un cookie authentiquement scellé peut être ancien : issu d'une version qui
   * admettait d'autres limites. « Nous l'avons écrit » n'est pas « il est encore
   * valide ».
   */
  it('refuse un panier de plus de lignes que la borne', () => {
    const trop = {
      ...newCart(),
      lines: Array.from({ length: MAX_CART_LINES + 1 }, (_valeur, index) => ({
        reference: `produit-${index}`,
        quantity: 1,
      })),
    };
    expect(() => unsealCart(sealCart(trop, SECRET), SECRET)).toThrow(CartError);
  });

  it.each([0, -1, 1000, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    'refuse la quantité %s',
    (quantite) => {
      const invalide = {
        ...newCart(),
        lines: [{ reference: 'filtre-a-huile', quantity: quantite }],
      };
      expect(() => unsealCart(sealCart(invalide, SECRET), SECRET)).toThrow(CartError);
    },
  );

  it.each([
    'Majuscule',
    'avec espace',
    'accentué',
    'double--tiret',
    '-debut',
    'fin-',
    'slash/dedans',
    '../../etc/passwd',
    '',
  ])('refuse la référence « %s »', (reference) => {
    const invalide = { ...newCart(), lines: [{ reference, quantity: 1 }] };
    expect(() => unsealCart(sealCart(invalide, SECRET), SECRET)).toThrow(CartError);
  });

  it('refuse une référence excessivement longue', () => {
    const invalide = {
      ...newCart(),
      lines: [{ reference: 'a'.repeat(200), quantity: 1 }],
    };
    expect(() => unsealCart(sealCart(invalide, SECRET), SECRET)).toThrow(CartError);
  });

  it('refuse un identifiant de panier qui n’est pas un UUID', () => {
    const invalide = { cartId: 'pas-un-uuid', lines: [] };
    expect(() => unsealCart(sealCart(invalide as Cart, SECRET), SECRET)).toThrow(
      CartError,
    );
  });

  it('refuse deux lignes portant la même référence', () => {
    const doublon = {
      ...newCart(),
      lines: [
        { reference: 'filtre-a-huile', quantity: 1 },
        { reference: 'filtre-a-huile', quantity: 5 },
      ],
    };
    expect(() => unsealCart(sealCart(doublon, SECRET), SECRET)).toThrow(CartError);
  });
});

describe('setLine', () => {
  it('ajoute une ligne', () => {
    const resultat = setLine(newCart(), 'filtre-a-huile', 3);
    expect(resultat.lines).toEqual([{ reference: 'filtre-a-huile', quantity: 3 }]);
  });

  it('modifie une ligne existante sans la déplacer', () => {
    const depart = panier([
      { reference: 'a-un', quantity: 1 },
      { reference: 'b-deux', quantity: 1 },
      { reference: 'c-trois', quantity: 1 },
    ]);
    const resultat = setLine(depart, 'b-deux', 9);
    expect(resultat.lines.map((l) => l.reference)).toEqual(['a-un', 'b-deux', 'c-trois']);
    expect(resultat.lines[1]).toEqual({ reference: 'b-deux', quantity: 9 });
  });

  it('retire la ligne à quantité zéro', () => {
    const depart = panier([
      { reference: 'a-un', quantity: 1 },
      { reference: 'b-deux', quantity: 2 },
    ]);
    const resultat = setLine(depart, 'a-un', 0);
    expect(resultat.lines).toEqual([{ reference: 'b-deux', quantity: 2 }]);
  });

  it('conserve l’identifiant du panier à travers les modifications', () => {
    const depart = newCart();
    const apres = setLine(setLine(depart, 'a-un', 1), 'a-un', 0);
    expect(apres.cartId).toBe(depart.cartId);
    expect(clearLines(apres).cartId).toBe(depart.cartId);
  });

  it('refuse une ligne de plus quand le panier est plein', () => {
    const plein = panier(
      Array.from({ length: MAX_CART_LINES }, (_valeur, index) => ({
        reference: `produit-${index}`,
        quantity: 1,
      })),
    );
    expect(() => setLine(plein, 'un-de-trop', 1)).toThrow(CartError);
  });

  it('accepte encore de modifier une ligne d’un panier plein', () => {
    const plein = panier(
      Array.from({ length: MAX_CART_LINES }, (_valeur, index) => ({
        reference: `produit-${index}`,
        quantity: 1,
      })),
    );
    // Contrôle négatif du précédent : sans lui, « plein » pourrait signifier
    // « figé », et un client ne pourrait plus corriger une quantité ni retirer
    // une ligne — donc plus jamais sortir de l'état plein.
    expect(setLine(plein, 'produit-0', 4).lines[0]).toEqual({
      reference: 'produit-0',
      quantity: 4,
    });
    expect(setLine(plein, 'produit-0', 0).lines).toHaveLength(MAX_CART_LINES - 1);
  });

  it('refuse une référence ou une quantité invalide', () => {
    expect(() => setLine(newCart(), 'Majuscule', 1)).toThrow(CartError);
    expect(() => setLine(newCart(), 'filtre-a-huile', 1000)).toThrow(CartError);
    expect(() => setLine(newCart(), 'filtre-a-huile', -1)).toThrow(CartError);
  });
});

describe('validateurs', () => {
  it('isValidReference', () => {
    expect(isValidReference('groupe-electrogene-5kva')).toBe(true);
    expect(isValidReference('a')).toBe(true);
    expect(isValidReference(42)).toBe(false);
    expect(isValidReference(null)).toBe(false);
    expect(isValidReference(undefined)).toBe(false);
  });

  it('isValidQuantity', () => {
    expect(isValidQuantity(1)).toBe(true);
    expect(isValidQuantity(MAX_LINE_QUANTITY)).toBe(true);
    expect(isValidQuantity(0)).toBe(false);
    expect(isValidQuantity('2')).toBe(false);
    expect(isValidQuantity(true)).toBe(false);
  });
});

describe('options du cookie', () => {
  it('est HttpOnly, SameSite=Lax et sans Domain', () => {
    const options = cartCookieOptions(true);
    expect(options.httpOnly).toBe(true);
    expect(options.secure).toBe(true);
    expect(options.sameSite).toBe('lax');
    expect(options.path).toBe('/');
    expect(options.maxAge).toBe(CART_MAX_AGE_SECONDS);
    // Aucun `Domain=` : le cookie reste lié à l'hôte exact. Le vérifier par
    // absence de clé, et non en comparant à `undefined`, ferait passer une clé
    // présente mais vide.
    expect('domain' in options).toBe(false);
  });

  it('n’exige pas Secure hors production, sinon rien ne fonctionne en local', () => {
    expect(cartCookieOptions(false).secure).toBe(false);
  });

  it('porte un nom distinct de celui du portail', () => {
    expect(CART_COOKIE).toBe('dt_shop_cart');
    expect(CART_COOKIE).not.toBe('dt_portal_session');
  });
});
