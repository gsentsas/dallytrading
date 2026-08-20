/**
 * Le cache des référentiels publics.
 *
 * Ce qui compte n'est pas qu'il mette en cache — c'est qu'il ne fasse jamais
 * échouer la page. Un formulaire ouvert avec une liste de ports vieille d'une
 * heure reste utilisable ; un formulaire qui ne s'ouvre pas ne l'est pas.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const listReferences = vi.fn();

vi.mock('@/services/odoo', () => ({
  getOdooGateway: () => ({ listReferences }),
}));
vi.mock('@/lib/logger', () => ({
  logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const { getPublicReferences, resetReferencesCache } = await import('./references-cache');

const PAYS = [{ code: 'SN', name: 'Sénégal' }];
const LIEUX = [
  {
    code: 'SNDKR', name: 'Dakar', city: 'Dakar', country_code: 'SN',
    state_code: 'DK', sea: true, air: false, road: false,
  },
];
const INCOTERMS = [{ code: 'FOB', name: 'FREE ON BOARD' }];

function repondre() {
  listReferences.mockImplementation((kind: string) =>
    Promise.resolve(
      kind === 'countries' ? PAYS : kind === 'locations' ? LIEUX : INCOTERMS,
    ),
  );
}

describe('getPublicReferences', () => {
  beforeEach(() => {
    listReferences.mockReset();
    resetReferencesCache();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('charge les trois référentiels en une fois', async () => {
    repondre();
    const references = await getPublicReferences('c1');

    expect(references.countries).toEqual(PAYS);
    expect(references.locations).toEqual(LIEUX);
    expect(references.incoterms).toEqual(INCOTERMS);
    expect(references.stale).toBe(false);
    expect(listReferences).toHaveBeenCalledTimes(3);
  });

  it('ne réinterroge pas l’ERP tant que la copie est fraîche', async () => {
    repondre();
    await getPublicReferences('c1');
    await getPublicReferences('c2');
    expect(listReferences).toHaveBeenCalledTimes(3);
  });

  it('sert la copie précédente quand l’ERP devient injoignable', async () => {
    repondre();
    await getPublicReferences('c1');

    vi.advanceTimersByTime(6 * 60 * 1000);
    listReferences.mockRejectedValue(new Error('ERP injoignable'));
    const references = await getPublicReferences('c2');

    expect(references.locations).toEqual(LIEUX);
    expect(references.stale).toBe(true);
  });

  it('rend des listes vides plutôt que de lever, sans copie utilisable', async () => {
    listReferences.mockRejectedValue(new Error('ERP injoignable'));
    const references = await getPublicReferences('c1');

    expect(references).toMatchObject({
      countries: [], locations: [], incoterms: [], stale: true,
    });
  });

  it('écarte une entrée non conforme sans perdre la liste', async () => {
    listReferences.mockImplementation((kind: string) =>
      Promise.resolve(
        kind === 'locations'
          ? [...LIEUX, { code: 'X', name: 'Intrus', vessel_id: 3 }]
          : kind === 'countries'
            ? PAYS
            : INCOTERMS,
      ),
    );
    const references = await getPublicReferences('c1');
    expect(references.locations).toEqual(LIEUX);
  });
});
