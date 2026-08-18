/**
 * L'adresse de l'image, et ce qu'elle ne doit jamais contenir.
 *
 * Les assertions négatives de ce fichier — pas de `product.template`, pas
 * d'identifiant, pas de `/web/image` — sont la raison d'être de tout le
 * mécanisme. Elles sont accompagnées d'un contrôle positif : sans lui,
 * « l'identifiant n'apparaît pas » serait vrai d'une URL vide.
 */

import { describe, expect, it } from 'vitest';

import {
  SHOP_IMAGE_DIMENSIONS,
  SHOP_IMAGE_MIME_TYPES,
  SHOP_IMAGE_SIZES,
  isShopImageMimeType,
  isShopImageSize,
  shopImageUrl,
} from './image';

const VERSION = 'a1b2c3d4e5f60718';

describe('shopImageUrl', () => {
  it('construit une adresse fondée sur le slug', () => {
    const url = shopImageUrl('groupe-electrogene-5kva', VERSION);

    expect(url).toBe(
      `/api/shop/products/groupe-electrogene-5kva/image?v=${VERSION}&size=card`,
    );
  });

  it('rend null sans image, pour que l’appelant n’émette aucune requête', () => {
    // Le substitut s'affiche alors sans aller-retour. Une URL menant à un 404
    // coûterait une requête par tuile et remplirait les journaux de refus qui
    // ne signalent rien.
    expect(shopImageUrl('un-produit', null)).toBeNull();
  });

  it('rend null sans référence', () => {
    expect(shopImageUrl('', VERSION)).toBeNull();
  });

  it('porte la taille demandée, et elle seule', () => {
    for (const size of SHOP_IMAGE_SIZES) {
      expect(shopImageUrl('un-produit', VERSION, size)).toContain(`size=${size}`);
    }
  });

  it('échappe une référence contenant des caractères d’URL', () => {
    // Le slug est contraint côté Odoo, mais cette fonction reçoit une chaîne :
    // une référence non échappée permettrait de sortir du chemin.
    const url = shopImageUrl('a/../../etc/passwd', VERSION);

    expect(url).not.toContain('../');
    expect(url).toContain('a%2F..%2F..%2Fetc%2Fpasswd');
  });

  it('change quand l’image change, et pas autrement', () => {
    const avant = shopImageUrl('un-produit', 'aaaaaaaaaaaaaaaa');
    const encore = shopImageUrl('un-produit', 'aaaaaaaaaaaaaaaa');
    const apres = shopImageUrl('un-produit', 'bbbbbbbbbbbbbbbb');

    // Stable : le navigateur garde son image tant que le contenu ne bouge pas.
    expect(encore).toBe(avant);
    // Différente : la nouvelle image est chargée sans que personne vide un cache.
    expect(apres).not.toBe(avant);
  });

  // ------------------------------------------------------------------
  // Ce que l'URL ne publie pas
  // ------------------------------------------------------------------

  it('contrôle positif : l’URL existe et porte bien la référence', () => {
    // Sans cette assertion, les trois suivantes seraient satisfaites par `null`.
    expect(shopImageUrl('groupe-5kva', VERSION)).toContain('groupe-5kva');
  });

  it('n’expose ni modèle ni identifiant technique', () => {
    const url = shopImageUrl('groupe-5kva', VERSION) ?? '';

    expect(url).not.toContain('product.template');
    expect(url).not.toContain('product.product');
    expect(url).not.toContain('image_1920');
  });

  it('n’emprunte pas la route générique d’Odoo', () => {
    // `/web/image/product.template/42/image_1920` est l'adresse qu'Odoo propose.
    // Elle publie le modèle et l'identifiant, et l'identifiant s'énumère : elle
    // servirait l'image d'un produit non publié à qui devine son numéro.
    expect(shopImageUrl('groupe-5kva', VERSION) ?? '').not.toContain('/web/image');
  });

  it('ne transporte aucune clé d’API', () => {
    const url = shopImageUrl('groupe-5kva', VERSION) ?? '';

    expect(url.toLowerCase()).not.toContain('api-key');
    expect(url.toLowerCase()).not.toContain('apikey');
    expect(url.toLowerCase()).not.toContain('token');
  });
});

describe('liste blanche des types', () => {
  it('accepte les types d’image servis', () => {
    for (const type of SHOP_IMAGE_MIME_TYPES) {
      expect(isShopImageMimeType(type)).toBe(true);
    }
  });

  it('tolère un paramètre accolé au type', () => {
    expect(isShopImageMimeType('image/png; charset=binary')).toBe(true);
    expect(isShopImageMimeType('IMAGE/PNG')).toBe(true);
  });

  it('refuse le SVG', () => {
    // Un SVG est un document XML capable de porter du script. Servi depuis notre
    // origine, il s'exécuterait dans notre contexte.
    expect(isShopImageMimeType('image/svg+xml')).toBe(false);
  });

  it('refuse tout ce qui n’est pas une image', () => {
    for (const type of ['text/html', 'application/json', 'text/plain', '', null]) {
      expect(isShopImageMimeType(type)).toBe(false);
    }
  });
});

describe('liste blanche des tailles', () => {
  it('reconnaît les tailles servies', () => {
    for (const size of SHOP_IMAGE_SIZES) {
      expect(isShopImageSize(size)).toBe(true);
    }
  });

  it('refuse une dimension libre', () => {
    // Une dimension arbitraire ferait redimensionner à la demande depuis
    // l'extérieur : chaque valeur inédite serait un calcul et une entrée de
    // cache de plus, pour qui itère de 1 à 4000.
    for (const valeur of ['2048', 'huge', '', 512, null, undefined, {}]) {
      expect(isShopImageSize(valeur)).toBe(false);
    }
  });

  it('donne une dimension d’affichage à chaque taille', () => {
    // Sans largeur ni hauteur, la grille du catalogue saute à l'arrivée des
    // images.
    for (const size of SHOP_IMAGE_SIZES) {
      expect(SHOP_IMAGE_DIMENSIONS[size].width).toBeGreaterThan(0);
      expect(SHOP_IMAGE_DIMENSIONS[size].height).toBeGreaterThan(0);
    }
  });
});
