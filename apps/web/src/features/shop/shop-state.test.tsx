import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ShopNotOpenYet, ShopUnavailable, EmptyCatalogue } from './ui';

/**
 * Les trois écrans de la vitrine sans produit, et ce qui les distingue.
 *
 * Le risque que ces tests ferment est précis : que « boutique fermée » et « panne »
 * se remettent à dire la même chose. C'est arrivé — la vitrine déployée mais
 * volontairement fermée annonçait « momentanément indisponible » en production.
 * Les assertions portent donc autant sur ce que chaque écran **ne dit pas** que
 * sur ce qu'il dit.
 */
describe('boutique en préparation', () => {
  const html = renderToStaticMarkup(<ShopNotOpenYet />);

  it('annonce une préparation, pas un incident', () => {
    expect(html).toContain('Boutique en préparation');
    expect(html).toContain('Notre catalogue sera bientôt disponible.');
  });

  it('ne parle jamais d’indisponibilité', () => {
    for (const interdit of ['indisponible', 'momentanément', 'réessayer', 'erreur']) {
      expect(html.toLowerCase()).not.toContain(interdit);
    }
  });

  it('donne quelque chose à faire au visiteur', () => {
    // « Réessayez » ne demande rien d'utile à quelqu'un devant une boutique qui
    // n'a jamais ouvert. Le devis, lui, est une porte réelle.
    expect(html).toContain('/devis');
    expect(html).toContain('Demander un devis');
  });

  it('n’est pas annoncé comme une alerte', () => {
    // `role="alert"` est réservé aux pannes : un lecteur d'écran l'interrompt.
    expect(html).not.toContain('role="alert"');
  });
});

describe('panne technique', () => {
  const html = renderToStaticMarkup(<ShopUnavailable />);

  it('dit clairement qu’il s’agit d’un incident passager', () => {
    expect(html).toContain('momentanément indisponible');
    expect(html).toContain('réessayer');
  });

  it('est annoncé comme une alerte', () => {
    expect(html).toContain('role="alert"');
  });

  it('ne se fait pas passer pour une boutique en préparation', () => {
    expect(html).not.toContain('Boutique en préparation');
    expect(html).not.toContain('bientôt disponible');
  });

  it('ne divulgue ni code, ni identifiant, ni infrastructure', () => {
    for (const interdit of ['shop_pricelist_missing', 'correlationId', 'odoo', 'crm.']) {
      expect(html.toLowerCase()).not.toContain(interdit.toLowerCase());
    }
  });
});

describe('boutique ouverte mais sans produit publié', () => {
  const html = renderToStaticMarkup(<EmptyCatalogue />);

  it('est un troisième écran, distinct des deux autres', () => {
    // Ouverte, configurée, simplement sans article publié — ni panne, ni
    // préparation.
    expect(html).not.toContain('Boutique en préparation');
    expect(html).not.toContain('momentanément indisponible');
    expect(html).not.toContain('role="alert"');
  });

  it('ne dit pas « aucun résultat »', () => {
    // Il n'y a pas de recherche : cette formulation laisserait croire qu'un
    // produit existe ailleurs.
    expect(html.toLowerCase()).not.toContain('aucun résultat');
  });
});
