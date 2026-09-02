import { describe, expect, it } from 'vitest';

import {
  LONGUEUR_REFERENCE_MAXIMALE, normaliserReference,
} from '@/lib/ops/legacy-intake';

/**
 * R3 · la référence, normalisée une seule fois.
 *
 * Le jeu de caractères n'est pas choisi : il est relevé sur les 52 références
 * réelles de production, qui n'emploient que lettres, chiffres, tiret et
 * souligné — cinq d'entre elles portent un souligné.
 */
describe('les références réelles passent', () => {
  it('accepte les formes rencontrées en production', () => {
    for (const reference of ['AIR-DSS-CDG-2026-002-A015', 'LEGACY-E2E-001',
                             'SN-DK_FR-PA_004', 'A012', 'SEA-DKR-LEH-2026-014-A007']) {
      expect(normaliserReference(reference), reference).toBe(reference);
    }
  });

  it('accepte le souligné, que cinq dossiers de production emploient', () => {
    // Une classe de caractères qui l'oublierait rendrait ces dossiers
    // inatteignables sans qu'aucun autre test ne s'en aperçoive.
    expect(normaliserReference('SN-DK_FR-PA_004')).toBe('SN-DK_FR-PA_004');
  });

  it('I2 · refuse les espaces de bordure, sans les rogner', () => {
    // Ceci est une identité d'URL. Rogner ferait pointer `%20A012%20` vers le
    // dossier `A012` : deux chemins pour une ressource, dont un que rien n'a
    // publié. La recherche, elle, peut rogner une saisie — ce n'est pas la
    // même chose.
    for (const bordee of [' A012', 'A012 ', '  A012  ', '\tA012', 'A012\n',
                          '\nA012', 'A012\t']) {
      expect(normaliserReference(bordee), JSON.stringify(bordee)).toBeNull();
    }
  });

  it('I2 · les formes réelles restent valides', () => {
    for (const bonne of ['A012', 'AIR-DSS-CDG-2026-002-A015',
                         'SN-DK_FR-PA_004', 'LEGACY-E2E-001']) {
      expect(normaliserReference(bonne), bonne).toBe(bonne);
    }
  });
});

describe('tout le reste est refusé, et refusé de la même façon', () => {
  it('refuse le vide, le trop long et les mauvais types', () => {
    for (const mauvaise of ['', '   ', null, undefined, 42, {}, [],
                            'A'.repeat(LONGUEUR_REFERENCE_MAXIMALE + 1)]) {
      expect(normaliserReference(mauvaise), JSON.stringify(mauvaise)).toBeNull();
    }
  });

  it('refuse ce qui pourrait composer un chemin ou une requête', () => {
    for (const mauvaise of ['../autre', 'A001/../A002', 'A/B', 'A001?x=1',
                            'A B', 'A%20B', 'A%2FB', 'A%ZZ', 'A|B',
                            '-A012', 'A012-', 'A--012']) {
      expect(normaliserReference(mauvaise), mauvaise).toBeNull();
    }
  });

  it('accepte exactement la borne, refuse un caractère de plus', () => {
    expect(normaliserReference('A'.repeat(LONGUEUR_REFERENCE_MAXIMALE)))
      .not.toBeNull();
    expect(normaliserReference('A'.repeat(LONGUEUR_REFERENCE_MAXIMALE + 1)))
      .toBeNull();
  });
});
