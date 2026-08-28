import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ListeDeparts } from '@/features/reception/ListeDeparts';
import type { Consolidation } from '@/lib/ops/consolidations';

const AERIEN: Consolidation = {
  reference: 'AIR-DSS-CDG-2026-002',
  transport_mode: 'air',
  direction: 'export',
  origin: { country_code: 'SN', city: 'Dakar', location: 'DSS' },
  destination: { country_code: 'FR', city: 'Paris', location: 'CDG' },
  collection_close_on: '2026-09-03',
  scheduled_departure: '2026-09-05T10:00:00Z',
};

const MARITIME: Consolidation = {
  ...AERIEN,
  reference: 'SEA-DKR-LEH-2026-001',
  transport_mode: 'sea',
  destination: { country_code: 'FR', city: 'Le Havre', location: 'LEH' },
  collection_close_on: '2026-09-18',
  scheduled_departure: null,
};

function rendu(consolidations: Consolidation[]): string {
  return renderToStaticMarkup(<ListeDeparts consolidations={consolidations} />);
}

describe('rendu d’un départ aérien', () => {
  const html = rendu([AERIEN]);

  it('annonce le mode en premier', () => {
    expect(html).toContain('Aérien');
  });

  it('montre la référence métier', () => {
    expect(html).toContain('AIR-DSS-CDG-2026-002');
  });

  it('montre la route en clair', () => {
    expect(html).toContain('Dakar');
    expect(html).toContain('Paris');
  });

  it('montre les deux échéances en toutes lettres', () => {
    expect(html).toContain('03 septembre 2026');
    expect(html).toContain('05 septembre 2026');
  });

  it('propose un bouton de sélection portant la référence', () => {
    expect(html).toContain('Sélectionner');
    expect(html).toContain('/reception/client?consolidation=AIR-DSS-CDG-2026-002');
  });
});

describe('rendu d’un départ maritime', () => {
  const html = rendu([MARITIME]);

  it('annonce le mode maritime', () => {
    expect(html).toContain('Maritime');
    expect(html).not.toContain('Aérien');
  });

  it('n’invente pas de date de départ quand il n’y en a pas', () => {
    expect(html).not.toContain('Départ prévu');
    expect(html).toContain('Collecte jusqu’au');
  });
});

describe('ce que l’écran ne montre jamais', () => {
  it('n’affiche pas la direction du départ', () => {
    // `direction` existe dans le DTO mais n'aide pas à choisir un départ.
    expect(rendu([AERIEN, MARITIME])).not.toContain('export');
  });

  it('montre la ville dans la route, jamais le code d’escale', () => {
    const routes = [...rendu([AERIEN, MARITIME]).matchAll(/class="route">([^<]*)</g)]
      .map((trouve) => trouve[1]);
    // DSS et CDG figurent dans la référence, qui est un identifiant ; ils
    // n'ont rien à faire dans la ligne que l'opérateur lit pour se décider.
    expect(routes).toEqual(['Dakar → Paris', 'Dakar → Le Havre']);
  });

  it('ne propose un bouton que pour les entrées renvoyées par le serveur', () => {
    const html = rendu([AERIEN, MARITIME]);
    expect(html.match(/Sélectionner/g)).toHaveLength(2);
    expect(rendu([]).match(/Sélectionner/g)).toBeNull();
  });

  it('n’offre aucun moyen d’ouvrir ou de fermer une collecte', () => {
    const html = rendu([AERIEN]);
    // Créer une consolidation reste une décision de back-office.
    for (const interdit of ['Créer', 'Nouvelle', 'Fermer', 'Clôturer', 'Supprimer']) {
      expect(html).not.toContain(interdit);
    }
  });
});
