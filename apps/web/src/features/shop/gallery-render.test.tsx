/**
 * Ce que le navigateur reçoit vraiment : le HTML de la tuile et de la galerie.
 *
 * Les tests d'ordre portent sur les fonctions pures ; ceux-ci portent sur le
 * rendu, et vérifient deux choses différentes :
 *
 * * que les décisions prises dans `gallery.ts` **arrivent** jusqu'au balisage —
 *   un tri correct dont le composant n'utiliserait pas le résultat serait
 *   invisible autrement ;
 * * qu'aucun identifiant technique, aucune adresse interne et aucune clé ne se
 *   glisse dans le document, y compris dans les attributs que personne ne
 *   regarde.
 *
 * Le clic sur une vignette n'est pas testé ici : la suite tourne sans DOM. Il
 * l'est en Playwright, sur un vrai navigateur, où il a un sens.
 */

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ProductGallery } from './ProductGallery';
import { ProductCard, ProductImage } from './ui';
import type { ShopProduct, ShopProductDetail } from '@/lib/shop/dto';

const PRINCIPALE = 'aaaa000000000001';
const G1 = 'bbbb000000000002';
const G2 = 'cccc000000000003';
const G3 = 'dddd000000000004';

const BASE: ShopProduct = {
  reference: 'camion-daf-lf-frigorifique',
  name: 'Camion DAF LF frigorifique',
  summary: 'Dix-huit tonnes, frigorifique.',
  price: 16000000,
  currency: 'XOF',
  stockPolicy: 'on_order',
  stockPolicyLabel: 'Sur commande',
  availability: 'on_order',
  imageVersion: PRINCIPALE,
  category: { reference: 'vehicules-industriels', name: 'Véhicules industriels' },
};

const DETAIL: ShopProductDetail = {
  ...BASE,
  description: 'Description commerciale.',
  unit: 'Units',
  gallery: [
    { reference: G3, sequence: 30 },
    { reference: G1, sequence: 10 },
    { reference: G2, sequence: 20 },
  ],
};

/**
 * Les `src` du document, entités HTML décodées.
 *
 * Le décodage n'est pas cosmétique : dans le balisage, les séparateurs de
 * paramètres sont écrits `&amp;`. Analysée telle quelle, une URL de galerie
 * donne un paramètre nommé `amp;v` et le jeton paraît absent — ce qu'une
 * première version de ce fichier a pris pour un bug du composant.
 */
function sources(html: string): string[] {
  return [...html.matchAll(/src="([^"]+)"/g)].map((m) =>
    (m[1] ?? '').replaceAll('&amp;', '&'),
  );
}

/** Les boutons du document, avec leurs attributs, un par entrée. */
function boutons(html: string): string[] {
  return [...html.matchAll(/<button\b[^>]*>/g)].map((m) => m[0]);
}

describe('tuile du catalogue', () => {
  const html = renderToStaticMarkup(<ProductCard product={BASE} />);

  it('affiche la photo principale', () => {
    const srcs = sources(html);

    expect(srcs).toHaveLength(1);
    expect(srcs[0]).toContain('/api/shop/products/camion-daf-lf-frigorifique/image');
    expect(srcs[0]).toContain(`v=${PRINCIPALE}`);
  });

  it('demande la taille de tuile, pas celle de la fiche', () => {
    // Servir une image de 1024 px dans une vignette de catalogue quadruplerait
    // le poids de la page pour un résultat identique à l'œil.
    expect(sources(html)[0]).toContain('size=card');
  });

  it('place l’image avant le nom du produit', () => {
    expect(html.indexOf('<img')).toBeLessThan(html.indexOf('Camion DAF LF frigorifique'));
  });

  it('ne charge aucune photo de galerie', () => {
    // La galerie n'est même pas dans le contrat de la liste ; cette assertion
    // le constate côté rendu, là où un développeur pressé pourrait la
    // réintroduire.
    for (const jeton of [G1, G2, G3]) {
      expect(html).not.toContain(jeton);
    }
    expect(html).not.toContain('gallery=');
  });
});

describe('substitut', () => {
  const html = renderToStaticMarkup(
    <ProductImage product={{ reference: 'un-produit', imageVersion: null }} />,
  );

  it('n’émet aucune requête d’image', () => {
    expect(html).not.toContain('<img');
    expect(html).not.toContain('/api/shop/products');
  });

  it('affiche un dessin, pas un vide', () => {
    expect(html).toContain('<svg');
    expect(html).toContain('aria-hidden="true"');
  });
});

describe('galerie de la fiche', () => {
  const html = renderToStaticMarkup(<ProductGallery product={DETAIL} />);
  const srcs = sources(html);

  it('rend quatre photos : la principale et les trois de galerie', () => {
    // Deux occurrences par photo dans les grandes images et les vignettes ;
    // c'est le nombre de photos distinctes qui compte.
    const jetons = new Set(
      srcs.map((s) => new URL(s, 'https://x').searchParams.get('v')),
    );

    expect(jetons.size).toBe(4);
  });

  it('respecte l’ordre : principale, puis séquence croissante', () => {
    const grandes = srcs.filter((s) => s.includes('size=detail'));

    expect(grandes).toHaveLength(4);
    expect(grandes[0]).toContain(`v=${PRINCIPALE}`);
    expect(grandes[0]).not.toContain('gallery=');
    expect(grandes[1]).toContain(`gallery=${G1}`);
    expect(grandes[2]).toContain(`gallery=${G2}`);
    expect(grandes[3]).toContain(`gallery=${G3}`);
  });

  it('propose des vignettes et des indicateurs quand il y a plusieurs photos', () => {
    expect(html).toContain('data-testid="vignettes"');
    expect(html).toContain('data-testid="indicateurs"');
    expect(html).toContain('Photo précédente');
    expect(html).toContain('Photo suivante');
  });

  it('désigne la première photo comme active au chargement', () => {
    // `aria-current` est ce que Playwright interrogera pour vérifier qu'un clic
    // sur une vignette déplace bien la sélection. Deux occurrences : la
    // vignette du bureau et l'indicateur du mobile, deux rendus du même état.
    const actifs = boutons(html).filter((b) => b.includes('aria-current="true"'));

    expect(actifs).toHaveLength(2);
    // L'assertion porte sur le bouton entier plutôt que sur ce qui précède
    // l'attribut : l'ordre des attributs dans le balisage n'est pas un contrat.
    for (const bouton of actifs) {
      expect(bouton).toContain('Photo 1 sur 4');
    }
  });

  it('charge la première photo sans attendre, les autres paresseusement', () => {
    expect(html).toContain('loading="eager"');
    expect((html.match(/loading="lazy"/g) ?? []).length).toBeGreaterThanOrEqual(3);
  });

  it('demande la grande taille pour l’affichage et la petite pour les vignettes', () => {
    expect(srcs.filter((s) => s.includes('size=detail'))).toHaveLength(4);
    expect(srcs.filter((s) => s.includes('size=card'))).toHaveLength(4);
  });
});

describe('galerie à une seule photo', () => {
  const html = renderToStaticMarkup(
    <ProductGallery product={{ ...DETAIL, gallery: [] }} />,
  );

  it('n’affiche ni flèches ni vignettes', () => {
    // Une flèche « suivante » qui ramène à la même image donne l'impression que
    // la page est cassée.
    expect(html).not.toContain('Photo suivante');
    expect(html).not.toContain('data-testid="vignettes"');
    expect(sources(html)).toHaveLength(1);
  });
});

describe('fiche sans aucune photo', () => {
  const html = renderToStaticMarkup(
    <ProductGallery product={{ ...DETAIL, imageVersion: null, gallery: [] }} />,
  );

  it('affiche le substitut, sans requête', () => {
    expect(html).not.toContain('<img');
    expect(html).toContain('<svg');
  });
});

describe('ce que le document ne contient jamais', () => {
  const html =
    renderToStaticMarkup(<ProductGallery product={DETAIL} />) +
    renderToStaticMarkup(<ProductCard product={BASE} />);

  it('contrôle positif : le document parle bien du produit', () => {
    expect(html).toContain('camion-daf-lf-frigorifique');
  });

  it('n’expose aucun identifiant ni chemin technique', () => {
    for (const interdit of [
      'product.template',
      'product.product',
      'dally.shop.product.image',
      'image_1920',
      '/web/image',
      'model=',
      'field=',
      'res_id',
    ]) {
      expect(html, interdit).not.toContain(interdit);
    }
  });

  it('ne transporte aucune clé ni adresse interne', () => {
    const bas = html.toLowerCase();
    for (const interdit of ['api-key', 'apikey', 'authorization', 'odoo', '8069']) {
      expect(bas, interdit).not.toContain(interdit);
    }
  });
});
