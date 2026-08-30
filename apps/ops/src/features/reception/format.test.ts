import { describe, expect, it } from 'vitest';

import { LIBELLE_MODE, enJour, enRoute } from '@/features/reception/format';

describe('affichage des dates', () => {
  it('écrit une date de collecte en toutes lettres', () => {
    expect(enJour('2026-09-03')).toBe('03 septembre 2026');
  });

  it('écrit un horodatage UTC au même jour', () => {
    // Dakar vit à UTC toute l'année : formater en UTC, c'est afficher l'heure
    // locale de ceux qui lisent l'écran.
    expect(enJour('2026-09-05T10:00:00Z')).toBe('05 septembre 2026');
  });

  it('ne décale pas la veille pour un départ de fin de journée', () => {
    // Le piège classique : un `new Date('2026-09-05')` interprété dans un
    // fuseau négatif afficherait le 04.
    expect(enJour('2026-09-05T23:30:00Z')).toBe('05 septembre 2026');
  });

  it('ne montre rien quand la date est absente', () => {
    expect(enJour(null)).toBeNull();
  });

  it('ne montre rien plutôt qu’une date illisible', () => {
    expect(enJour('pas-une-date')).toBeNull();
  });
});

describe('affichage de la route', () => {
  const lieu = (city: string, location: string, country_code: string) => ({
    city, location, country_code,
  });

  it('préfère la ville au code d’escale', () => {
    // Un logisticien connaît Paris, pas forcément CDG.
    expect(enRoute(lieu('Dakar', 'DSS', 'SN'), lieu('Paris', 'CDG', 'FR')))
      .toBe('Dakar → Paris');
  });

  it('retombe sur le code d’escale quand la ville manque', () => {
    expect(enRoute(lieu('', 'DSS', 'SN'), lieu('', 'CDG', 'FR'))).toBe('DSS → CDG');
  });

  it('retombe sur le pays quand tout le reste manque', () => {
    expect(enRoute(lieu('', '', 'SN'), lieu('', '', 'FR'))).toBe('SN → FR');
  });

  it('n’affiche jamais une flèche seule', () => {
    expect(enRoute(lieu('', '', ''), lieu('', '', ''))).toBe('— → —');
  });
});

describe('libellés de mode', () => {
  it('ne connaît que les modes colis', () => {
    expect(Object.keys(LIBELLE_MODE).sort()).toEqual(['air', 'sea']);
    expect(LIBELLE_MODE.air).toBe('Aérien');
    expect(LIBELLE_MODE.sea).toBe('Maritime');
  });
});
