import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

/**
 * `usePathname` est un hook de Next : il n'existe pas hors d'une requête. Le
 * simuler est le seul moyen de rendre ce composant en test, et il ne change rien
 * à ce qui est vérifié — la présence et l'ordre des sections.
 */
vi.mock('next/navigation', () => ({
  usePathname: () => '/espace-client/commandes',
}));

/**
 * `LogoutButton` fait un appel réseau au clic. Il n'est pas l'objet de ce test, et
 * le laisser tel quel ferait dépendre le rendu d'un `fetch` global.
 */
vi.mock('./LogoutButton', () => ({
  LogoutButton: () => null,
}));

const { PortalNav } = await import('./PortalNav');

function rendu() {
  return renderToStaticMarkup(<PortalNav name="Client Test" company="Test SARL" />);
}

describe('navigation de l’espace client', () => {
  it('expose la section Commandes', () => {
    const html = rendu();
    expect(html).toContain('/espace-client/commandes');
    expect(html).toContain('Commandes');
  });

  /**
   * Le vrai risque de cette tranche : ajouter une section en cassant les autres.
   * Le test les nomme toutes, pour qu'une disparition soit un échec et non une
   * découverte en production.
   */
  it('ne casse aucune section existante', () => {
    const html = rendu();
    for (const [href, label] of [
      ['/espace-client', 'Tableau de bord'],
      ['/espace-client/devis', 'Devis'],
      ['/espace-client/sourcing', 'Sourcing'],
      ['/espace-client/trading', 'Trading'],
      ['/espace-client/expeditions', 'Expéditions'],
      ['/espace-client/documents', 'Documents'],
      ['/espace-client/profil', 'Profil'],
    ]) {
      expect(html, `la section « ${label} » a disparu`).toContain(href);
      expect(html, `le libellé « ${label} » a disparu`).toContain(label);
    }
  });

  it('n’introduit pas une seconde navigation', () => {
    // Une navigation parallèle serait le symptôme d'une boutique greffée à côté
    // de l'espace client plutôt qu'intégrée dedans.
    const html = rendu();
    const navigations = html.match(/<nav\b/g) ?? [];
    expect(navigations.length).toBeLessThanOrEqual(1);
  });

  it('marque la page courante pour les lecteurs d’écran', () => {
    // `aria-current` plutôt qu'une couleur : un lecteur d'écran annonce alors la
    // position, ce qu'une classe CSS ne fait pas.
    expect(rendu()).toContain('aria-current="page"');
  });

  it('place Commandes juste après Devis', () => {
    // L'ordre suit le parcours client — on demande un devis, puis on commande.
    const html = rendu();
    const devis = html.indexOf('/espace-client/devis');
    const commandes = html.indexOf('/espace-client/commandes');
    const sourcing = html.indexOf('/espace-client/sourcing');
    expect(devis).toBeGreaterThan(-1);
    expect(commandes).toBeGreaterThan(devis);
    expect(commandes).toBeLessThan(sourcing);
  });
});
