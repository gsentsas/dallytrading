import { describe, expect, it } from 'vitest';

import {
  CHIFFRES_MINIMUM,
  chiffres,
  emailUtilisable,
  telephoneUtilisable,
} from '@/features/reception/telephone';

describe('validation locale du téléphone', () => {
  it('exige neuf chiffres significatifs', () => {
    expect(CHIFFRES_MINIMUM).toBe(9);
  });

  it.each([
    '+221 77 123 45 67',
    '00221771234567',
    '221771234567',
    '77 123 45 67',
    '+33 6 12 34 56 78',
    '06 12 34 56 78',
  ])('accepte %s', (saisie) => {
    expect(telephoneUtilisable(saisie)).toBe(true);
  });

  it.each(['', '77', '0612', '77123456', '   '])('refuse %s', (saisie) => {
    // Ce qui est refusé ici n'est jamais envoyé : « 77 » rapprocherait la
    // moitié du fichier, et l'opérateur l'apprend sans aller-retour réseau.
    expect(telephoneUtilisable(saisie)).toBe(false);
  });

  it('ne retient que les chiffres', () => {
    expect(chiffres('+221 77-123.45 67')).toBe('221771234567');
  });
});

describe('validation locale de l’adresse', () => {
  it.each(['client@example.com', 'a.b+c@sous.domaine.test'])('accepte %s', (saisie) => {
    expect(emailUtilisable(saisie)).toBe(true);
  });

  it.each(['client', 'client@', '@example.com', 'client@example', 'a@@b.com', ''])(
    'refuse %s', (saisie) => {
      expect(emailUtilisable(saisie)).toBe(false);
    });
});
