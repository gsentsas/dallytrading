/**
 * L'ordre des photos et la navigation, sans navigateur.
 *
 * Ces tests portent sur des fonctions pures, et c'est délibéré : la suite tourne
 * en environnement Node, sans DOM. Enfermer l'ordre des photos dans le composant
 * client aurait rendu la règle « la principale d'abord » vérifiable seulement en
 * Playwright — c'est-à-dire tard, lentement, et seulement si quelqu'un pense à
 * regarder.
 */

import { describe, expect, it } from 'vitest';

import {
  indexValide,
  photoPrecedente,
  photoSuivante,
  photosDuProduit,
} from './gallery';

const PRINCIPALE = 'aaaa000000000001';
const G1 = 'bbbb000000000002';
const G2 = 'cccc000000000003';
const G3 = 'dddd000000000004';

function produit(options: {
  imageVersion?: string | null;
  gallery?: Array<{ reference: string; sequence: number }>;
} = {}) {
  return {
    reference: 'camion-daf-lf-frigorifique',
    imageVersion: options.imageVersion === undefined ? PRINCIPALE : options.imageVersion,
    gallery: options.gallery ?? [],
  };
}

describe('ordre des photos', () => {
  it('place la photo principale en premier', () => {
    // C'est le visage du produit, choisi comme tel. Le laisser dépendre d'un
    // numéro d'ordre saisi ailleurs ferait changer la vitrine sans qu'on ait
    // touché à la vitrine.
    const photos = photosDuProduit(
      produit({ gallery: [{ reference: G1, sequence: 1 }] }),
    );

    expect(photos).toHaveLength(2);
    expect(photos[0]?.token).toBe(PRINCIPALE);
    expect(photos[0]?.principale).toBe(true);
    expect(photos[1]?.token).toBe(G1);
  });

  it('trie la galerie par séquence, pas par ordre d’arrivée', () => {
    const photos = photosDuProduit(
      produit({
        gallery: [
          { reference: G3, sequence: 30 },
          { reference: G1, sequence: 10 },
          { reference: G2, sequence: 20 },
        ],
      }),
    );

    expect(photos.map((p) => p.token)).toEqual([PRINCIPALE, G1, G2, G3]);
  });

  it('départage les ex æquo de façon stable', () => {
    // Deux rendus successifs doivent donner le même ordre : un tri instable se
    // verrait comme des vignettes qui changent de place au rechargement.
    const galerie = [
      { reference: G2, sequence: 10 },
      { reference: G1, sequence: 10 },
    ];
    const premier = photosDuProduit(produit({ gallery: galerie }));
    const second = photosDuProduit(produit({ gallery: [...galerie].reverse() }));

    expect(premier.map((p) => p.token)).toEqual(second.map((p) => p.token));
  });

  it('ne modifie pas le tableau reçu', () => {
    // La projection vient d'un Server Component ; la trier en place muterait un
    // objet partagé avec le rendu.
    const galerie = [
      { reference: G3, sequence: 30 },
      { reference: G1, sequence: 10 },
    ];
    photosDuProduit(produit({ gallery: galerie }));

    expect(galerie[0]?.reference).toBe(G3);
  });

  it('sert la galerie seule quand il n’y a pas de photo principale', () => {
    const photos = photosDuProduit(
      produit({ imageVersion: null, gallery: [{ reference: G1, sequence: 10 }] }),
    );

    expect(photos).toHaveLength(1);
    expect(photos[0]?.principale).toBe(false);
  });

  it('rend un tableau vide sans aucune photo', () => {
    // Le signal du substitut. Il ne coûte aucune requête réseau.
    expect(photosDuProduit(produit({ imageVersion: null }))).toEqual([]);
  });

  it('écarte une photo dont l’adresse ne peut pas être construite', () => {
    // Un jeton vide donnerait une URL sans jeton, donc une vignette morte.
    const photos = photosDuProduit(
      produit({ gallery: [{ reference: '', sequence: 10 }] }),
    );

    expect(photos.map((p) => p.token)).toEqual([PRINCIPALE]);
  });
});

describe('adresses produites', () => {
  const photos = photosDuProduit(
    produit({ gallery: [{ reference: G1, sequence: 10 }] }),
  );

  it('donne deux tailles par photo', () => {
    for (const photo of photos) {
      expect(photo.card).toContain('size=card');
      expect(photo.detail).toContain('size=detail');
    }
  });

  it('distingue la photo principale des photos de galerie', () => {
    // La principale n'a pas de paramètre `gallery` : c'est `image_1920` du
    // produit, et lui inventer un jeton de galerie ferait chercher une photo
    // qui n'existe pas.
    expect(photos[0]?.detail).not.toContain('gallery=');
    expect(photos[1]?.detail).toContain(`gallery=${G1}`);
  });

  it('n’expose aucun identifiant technique', () => {
    const toutes = photos.map((p) => `${p.card} ${p.detail}`).join(' ');

    // Contrôle positif d'abord : sans lui, les assertions négatives seraient
    // satisfaites par une chaîne vide.
    expect(toutes).toContain('camion-daf-lf-frigorifique');
    for (const interdit of [
      'product.template',
      'dally.shop.product.image',
      'image_1920',
      '/web/image',
      'model=',
      'field=',
      'id=',
    ]) {
      expect(toutes).not.toContain(interdit);
    }
  });

  it('ne transporte aucune clé d’API', () => {
    const toutes = photos.map((p) => `${p.card} ${p.detail}`).join(' ').toLowerCase();

    expect(toutes).not.toContain('api-key');
    expect(toutes).not.toContain('apikey');
    expect(toutes).not.toContain('token=');
  });
});

describe('navigation', () => {
  it('avance et recule en boucle', () => {
    // Buter sur la dernière obligerait à revenir en arrière autant de fois pour
    // revoir la première.
    expect(photoSuivante(0, 4)).toBe(1);
    expect(photoSuivante(3, 4)).toBe(0);
    expect(photoPrecedente(0, 4)).toBe(3);
    expect(photoPrecedente(2, 4)).toBe(1);
  });

  it('reste à zéro sans photo', () => {
    // Le composant appelle ces fonctions avant de savoir s'il a des photos ;
    // un NaN se propagerait jusqu'à un `scrollTo` silencieusement inopérant.
    for (const total of [0, -1]) {
      expect(photoSuivante(0, total)).toBe(0);
      expect(photoPrecedente(0, total)).toBe(0);
      expect(indexValide(3, total)).toBe(0);
    }
  });

  it('borne un index venu de l’extérieur', () => {
    expect(indexValide(-5, 3)).toBe(0);
    expect(indexValide(99, 3)).toBe(2);
    expect(indexValide(1.5, 3)).toBe(0);
  });
});
