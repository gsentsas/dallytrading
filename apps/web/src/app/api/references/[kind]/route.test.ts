/**
 * La route BFF des référentiels.
 *
 * Trois questions, et rien d'autre : est-ce que seuls les quatre référentiels
 * déclarés passent, est-ce qu'une entrée non conforme est écartée sans faire
 * tomber la liste, et est-ce qu'une panne d'Odoo laisse le formulaire
 * utilisable.
 *
 * La quatrième — « aucune donnée interne ne sort » — est vérifiée ici sur la
 * réponse HTTP réelle, et non seulement sur le schéma : c'est la sortie du
 * serveur qui compte, pas l'intention.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const listReferences = vi.fn();

vi.mock('@/services/odoo', () => ({
  getOdooGateway: () => ({ listReferences }),
}));

vi.mock('@/lib/logger', () => ({
  logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn() },
  newCorrelationId: () => 'test-correlation',
}));

const { GET } = await import('./route');

function requete(kind: string, query = ''): [Request, { params: Promise<{ kind: string }> }] {
  return [
    new Request(`https://dallytrading.com/api/references/${kind}${query}`),
    { params: Promise.resolve({ kind }) },
  ];
}

describe('GET /api/references/<kind>', () => {
  beforeEach(() => {
    listReferences.mockReset();
  });

  it('sert un référentiel déclaré', async () => {
    listReferences.mockResolvedValue([{ code: 'SN', name: 'Sénégal' }]);
    const reponse = await GET(...requete('countries'));

    expect(reponse.status).toBe(200);
    expect(await reponse.json()).toEqual({ countries: [{ code: 'SN', name: 'Sénégal' }] });
    expect(reponse.headers.get('cache-control')).toBe('public, max-age=300');
  });

  it('transmet l’argument, borné en longueur', async () => {
    listReferences.mockResolvedValue([]);
    await GET(...requete('states', '?q=SN'));
    expect(listReferences).toHaveBeenCalledWith('states', 'SN', 'test-correlation');

    listReferences.mockClear();
    await GET(...requete('locations', `?q=${'x'.repeat(200)}`));
    const argument = listReferences.mock.calls[0]?.[1] as string;
    expect(argument.length).toBeLessThanOrEqual(40);
  });

  it('refuse un référentiel inconnu sans appeler l’ERP', async () => {
    for (const kind of ['carriers', 'vessels', 'airlines', 'routes', 'costs']) {
      const reponse = await GET(...requete(kind));
      expect(reponse.status).toBe(404);
    }
    expect(listReferences).not.toHaveBeenCalled();
  });

  it('écarte une entrée non conforme sans perdre les autres', async () => {
    listReferences.mockResolvedValue([
      { code: 'SN', name: 'Sénégal' },
      { code: 'CI', name: 'Côte d’Ivoire', carrier_partner_id: 3 },
      { code: '', name: 'Vide' },
    ]);
    const charge = (await (await GET(...requete('countries'))).json()) as {
      countries: unknown[];
    };
    expect(charge.countries).toEqual([{ code: 'SN', name: 'Sénégal' }]);
  });

  it('ne laisse jamais sortir un champ interne', async () => {
    listReferences.mockResolvedValue([
      {
        code: 'SNDKR', name: 'Dakar', city: 'Dakar', country_code: 'SN',
        state_code: 'DK', sea: true, air: false, road: false,
        carrier_partner_id: 3, vessel_id: 9, cost: 1200,
      },
    ]);
    const texte = await (await GET(...requete('locations', '?q=sea'))).text();
    for (const interdit of ['carrier', 'vessel', 'cost', 'margin', 'airline']) {
      expect(texte).not.toContain(interdit);
    }
  });

  it('rend une liste vide quand l’ERP tombe, pour que le formulaire reste ouvert', async () => {
    listReferences.mockRejectedValue(new Error('ERP indisponible'));
    const reponse = await GET(...requete('locations'));

    expect(reponse.status).toBe(200);
    expect(await reponse.json()).toEqual({ locations: [] });
    // Une panne d'une minute ne doit pas être mise en cache cinq.
    expect(reponse.headers.get('cache-control')).toBe('no-store');
  });
});
