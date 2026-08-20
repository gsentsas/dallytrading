/**
 * Les référentiels publics : ce que la vitrine accepte, et ce qu'elle refuse.
 *
 * Le schéma est la seconde barrière — Odoo décide ce qu'il publie, celle-ci
 * décide ce qui traverse. Les assertions vont donc par paires : une entrée
 * conforme passe, et une entrée qui porte un champ de trop est rejetée. Sans la
 * seconde, `.strict()` pourrait disparaître sans qu'aucun test ne bronche.
 */

import { describe, expect, it } from 'vitest';

import {
  isPublicMode,
  isReferenceKind,
  locationsForMode,
  modeForService,
  referenceCountrySchema,
  referenceIncotermSchema,
  referenceLocationSchema,
  referenceStateSchema,
  type ReferenceLocation,
} from './dto';

const dakar: ReferenceLocation = {
  code: 'SNDKR', name: 'Port autonome de Dakar', city: 'Dakar',
  country_code: 'SN', state_code: 'DK', sea: true, air: false, road: false,
};
const dss: ReferenceLocation = {
  code: 'DSS', name: 'Aéroport international Blaise Diagne', city: 'Diass',
  country_code: 'SN', state_code: 'TH', sea: false, air: true, road: false,
};
const routier: ReferenceLocation = {
  code: 'MLBKO', name: 'Bamako terminal', city: 'Bamako',
  country_code: 'ML', state_code: null, sea: false, air: false, road: true,
};

describe('schémas', () => {
  it('accepte un pays, une région et un incoterm bien formés', () => {
    expect(referenceCountrySchema.parse({ code: 'SN', name: 'Sénégal' })).toEqual({
      code: 'SN', name: 'Sénégal',
    });
    expect(referenceStateSchema.parse({ code: 'DK', name: 'Dakar' }).code).toBe('DK');
    expect(
      referenceIncotermSchema.parse({ code: 'FOB', name: 'FREE ON BOARD' }).code,
    ).toBe('FOB');
  });

  it('accepte un lieu complet, drapeaux compris', () => {
    expect(referenceLocationSchema.parse(dakar)).toEqual(dakar);
  });

  it('accepte une ville et une région absentes', () => {
    const sansRegion = { ...dakar, city: null, state_code: null };
    expect(referenceLocationSchema.parse(sansRegion).state_code).toBeNull();
  });

  it('refuse tout champ non déclaré', () => {
    // C'est LE test du `.strict()` : un champ interne qui apparaîtrait côté
    // serveur ne doit pas traverser en silence.
    for (const intrus of [
      { carrier_partner_id: 3 },
      { vessel_id: 12 },
      { airline_id: 4 },
      { cost: 1200 },
      { id: 7 },
    ]) {
      expect(
        referenceLocationSchema.safeParse({ ...dakar, ...intrus }).success,
      ).toBe(false);
    }
  });

  it('refuse un code vide ou un nom manquant', () => {
    expect(referenceCountrySchema.safeParse({ code: '', name: 'X' }).success).toBe(false);
    expect(referenceCountrySchema.safeParse({ code: 'SN' }).success).toBe(false);
  });
});

describe('filtrage par mode', () => {
  const tous = [dakar, dss, routier];

  it('ne garde que les lieux du mode', () => {
    expect(locationsForMode(tous, 'sea')).toEqual([dakar]);
    expect(locationsForMode(tous, 'air')).toEqual([dss]);
    expect(locationsForMode(tous, 'road')).toEqual([routier]);
  });

  it('sans mode, ne filtre rien', () => {
    expect(locationsForMode(tous, undefined)).toHaveLength(3);
  });

  it('un port maritime ne peut pas apparaître en aérien, et réciproquement', () => {
    expect(locationsForMode(tous, 'air')).not.toContain(dakar);
    expect(locationsForMode(tous, 'sea')).not.toContain(dss);
  });
});

describe('mode déduit du service', () => {
  it('lit le mode du service quand il le porte', () => {
    expect(modeForService('freight_sea', undefined)).toBe('sea');
    expect(modeForService('freight_air', undefined)).toBe('air');
  });

  it('lit le sous-mode pour le groupage', () => {
    expect(modeForService('freight_groupage', 'sea')).toBe('sea');
    expect(modeForService('freight_groupage', 'air')).toBe('air');
  });

  it('ne devine rien quand le mode ne se déduit pas', () => {
    // Un groupage dont le sous-mode n'est pas encore choisi, un service de
    // conseil, un transport de véhicule : aucun repli silencieux.
    expect(modeForService('freight_groupage', undefined)).toBeUndefined();
    expect(modeForService('freight_vehicle', undefined)).toBeUndefined();
    expect(modeForService('logistics', undefined)).toBeUndefined();
    expect(modeForService(undefined, undefined)).toBeUndefined();
  });
});

describe('gardes de type', () => {
  it('reconnaît les quatre référentiels et rien d’autre', () => {
    for (const kind of ['countries', 'states', 'locations', 'incoterms']) {
      expect(isReferenceKind(kind)).toBe(true);
    }
    for (const kind of ['carriers', 'vessels', 'airlines', 'routes', '__proto__']) {
      expect(isReferenceKind(kind)).toBe(false);
    }
  });

  it('reconnaît les trois modes publics', () => {
    expect(isPublicMode('sea')).toBe(true);
    expect(isPublicMode('ocean')).toBe(false);
    expect(isPublicMode('vehicle')).toBe(false);
  });
});
