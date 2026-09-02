import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  creerSuiviDeGestes,
  departComplet,
  determinerAffichage,
  gesteProposé,
  interpreterEnvoi,
  libelleGeste,
  libelleStatut,
  lireChargement,
  resteALire,
  resumeLisible,
} from '@/features/chargement/chargement-vocabulaire';

const SOURCE = readFileSync(
  fileURLToPath(new URL('./ChargementDepart.tsx', import.meta.url)), 'utf8');

const RESUME = {
  shipments_expected: 2, shipments_complete: 1,
  packages_expected: 18, packages_loaded: 12, packages_partial: 1,
  packages_remaining: 4, packages_blocked: 1,
  quantity_expected: 20, quantity_loaded: 14,
  weight_expected_kg: 100, weight_loaded_kg: 70,
  volume_expected_cbm: 1, volume_loaded_cbm: 0.7,
};

const COLIS = {
  reference: 'abc', description: 'Savon', goods_category: 'Non alimentaire',
  package_type: 'parcel', expected_quantity: 2, loaded_quantity: 0,
  remaining_quantity: 2, exact_weight_kg: 13.5, volume_cbm: 0.04,
  status: 'not_loaded' as const, can_load: true, can_unload: false,
  blocker: null,
};

describe('le compte, jamais le pourcentage', () => {
  it('se lit comme une pile se vérifie', () => {
    expect(resumeLisible(RESUME)).toBe('12 sur 18 colis');
  });

  it('dit ce qui manque, et sous quelle forme', () => {
    expect(resteALire(RESUME)).toBe('4 à charger · 1 partiel · 1 bloqué');
    expect(resteALire({ ...RESUME, packages_partial: 2, packages_blocked: 3 }))
      .toContain('2 partiels');
    expect(resteALire({ ...RESUME, packages_partial: 2, packages_blocked: 3 }))
      .toContain('3 bloqués');
  });

  it('ne dit rien quand il n’y a rien à dire', () => {
    expect(resteALire({
      ...RESUME, packages_remaining: 0, packages_partial: 0, packages_blocked: 0,
    })).toBe('');
  });

  it('un départ n’est complet que si tout y est', () => {
    expect(departComplet(RESUME)).toBe(false);
    expect(departComplet({ ...RESUME, packages_loaded: 18 })).toBe(true);
    // Un départ sans aucun colis attendu n'est pas « complet » : il est vide.
    expect(departComplet({ ...RESUME, packages_expected: 0, packages_loaded: 0 }))
      .toBe(false);
  });

  it('aucune fonction ne calcule de taux', () => {
    const vocabulaire = readFileSync(fileURLToPath(
      new URL('./chargement-vocabulaire.ts', import.meta.url)), 'utf8');
    const sansCommentaires = vocabulaire
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    for (const interdit of ['* 100', 'Math.round', 'toFixed', '%']) {
      expect(sansCommentaires, interdit).not.toContain(interdit);
    }
  });
});

describe('le serveur décide, l’écran obéit', () => {
  it('le geste proposé sort de `can_load` / `can_unload`', () => {
    expect(gesteProposé(COLIS)).toBe('load');
    expect(gesteProposé({ ...COLIS, can_load: false, can_unload: true }))
      .toBe('unload');
    expect(gesteProposé({ ...COLIS, can_load: false, can_unload: false }))
      .toBeNull();
  });

  it('un colis bloqué ne propose aucun geste', () => {
    expect(gesteProposé({
      ...COLIS, status: 'blocked', can_load: false, can_unload: false,
      blocker: 'Déjà chargé sur un autre départ actif.',
    })).toBeNull();
  });

  it('les statuts se lisent en mots', () => {
    expect(libelleStatut('loaded')).toBe('Chargé');
    expect(libelleStatut('not_loaded')).toBe('À charger');
    expect(libelleStatut('partial')).toBe('Partiel');
    expect(libelleStatut('blocked')).toBe('Bloqué');
    // Un statut inconnu se montre tel quel plutôt que de disparaître.
    expect(libelleStatut('inconnu')).toBe('inconnu');
  });

  it('les deux gestes, et rien d’autre', () => {
    expect(libelleGeste('load')).toBe('CHARGER');
    expect(libelleGeste('unload')).toBe('RETIRER');
  });
});

describe('une lecture qui échoue n’est pas un départ vide', () => {
  const DETAIL = {
    reference: 'AIR-DSS-CDG-2026-002', state: 'collecting',
    state_label: 'Collecte ouverte', transport_mode: 'air', direction: 'export',
    origin: { country_code: 'SN', city: 'Dakar', location: 'DSS' },
    destination: { country_code: 'FR', city: 'Paris', location: 'CDG' },
    collection_close_on: '', scheduled_departure: '', can_load: true,
    summary: RESUME, shipments: [],
  };

  it('rend les données quand le serveur a répondu', async () => {
    expect(await lireChargement(async () => ({
      ok: true, corps: { success: true, data: { loading: DETAIL } },
    }))).toEqual({ issue: 'ok', donnees: DETAIL });
  });

  it.each([
    ['HTTP 503', async () => ({ ok: false, corps: null })],
    ['HTTP 200 avec success=false', async () => ({
      ok: true, corps: { success: false, error: 'Session expirée.' },
    })],
    ['enveloppe sans `loading`', async () => ({
      ok: true, corps: { success: true, data: {} },
    })],
    ['exception réseau', async () => { throw new TypeError('Failed to fetch'); }],
  ] as const)('%s affiche l’indisponibilité, jamais le vide',
    async (_scenario, appeler) => {
      const resultat = await lireChargement(appeler);
      expect(resultat).toEqual({ issue: 'echec' });
      expect(determinerAffichage({
        chargement: false, lectureEchouee: true, detail: null,
      })).toMatchObject({ indisponible: true, aucunDossier: false, liste: false });
    });

  it('un vrai succès vide affiche le vide, pas l’indisponibilité', () => {
    expect(determinerAffichage({
      chargement: false, lectureEchouee: false, detail: DETAIL,
    })).toMatchObject({ indisponible: false, aucunDossier: true, liste: false });
  });

  it('pendant le chargement, ni vide ni indisponible', () => {
    expect(determinerAffichage({
      chargement: true, lectureEchouee: false, detail: null,
    })).toEqual({
      indisponible: false, aucunDossier: false, liste: false, ferme: false,
    });
  });

  it('une collecte close se dit, et la liste reste lisible', () => {
    const ferme = {
      ...DETAIL, can_load: false,
      shipments: [{
        reference: 'A001', local_reference: 'A001',
        customer: { name: 'Fatou' }, complete: true, packages: [],
      }],
    };
    expect(determinerAffichage({
      chargement: false, lectureEchouee: false, detail: ferme,
    })).toMatchObject({ ferme: true, liste: true, indisponible: false });
  });
});

describe('ce que l’opérateur lit après un geste', () => {
  it('reprend le message du serveur, qui seul sait pourquoi il refuse', () => {
    expect(interpreterEnvoi(false, {
      success: false, error: 'La collecte de ce départ n’est plus ouverte.',
    })).toEqual({
      issue: 'refus', message: 'La collecte de ce départ n’est plus ouverte.',
    });
  });

  it('garantit un message même quand le serveur n’en donne aucun', () => {
    const issue = interpreterEnvoi(false, null);
    expect(issue.issue).toBe('refus');
    expect(issue).toHaveProperty('message');
  });

  it('un succès rend le départ recalculé, pas un fragment', () => {
    const issue = interpreterEnvoi(true, {
      success: true, data: { loading: { reference: 'X' } },
    });
    expect(issue).toEqual({ issue: 'ok', donnees: { reference: 'X' } });
  });

  it('un succès sans départ est traité comme un refus', () => {
    expect(interpreterEnvoi(true, { success: true, data: {} }).issue).toBe('refus');
  });
});

describe('l’identifiant d’un geste', () => {
  function suivi() {
    let rang = 0;
    return creerSuiviDeGestes(() => `geste-${(rang += 1)}`);
  }

  it('une reprise réseau rejoue exactement le même geste', () => {
    const gestes = suivi();
    expect(gestes.identifiant('colis-a', 'load')).toBe('geste-1');
    expect(gestes.identifiant('colis-a', 'load')).toBe('geste-1');
  });

  it('deux colis ne sont pas la même intention', () => {
    const gestes = suivi();
    expect(gestes.identifiant('colis-a', 'load')).toBe('geste-1');
    expect(gestes.identifiant('colis-b', 'load')).toBe('geste-2');
  });

  it('charger et retirer ne sont pas la même intention', () => {
    const gestes = suivi();
    expect(gestes.identifiant('colis-a', 'load')).toBe('geste-1');
    expect(gestes.identifiant('colis-a', 'unload')).toBe('geste-2');
  });

  it('un geste abouti en ouvre un neuf', () => {
    const gestes = suivi();
    const avant = gestes.identifiant('colis-a', 'load');
    gestes.terminer('colis-a', 'load');
    expect(gestes.identifiant('colis-a', 'load')).not.toBe(avant);
  });

  it('le composant ne clôt le geste que sur un succès', () => {
    const bloc = SOURCE.slice(SOURCE.indexOf('async function appliquer('));
    const succes = bloc.slice(bloc.indexOf("if (issue.issue === 'ok')"));
    expect(succes.slice(0, succes.indexOf('return;')))
      .toContain('gestes.current.terminer(');
    // Un échec réseau conserve l'identifiant : c'est ce qui rend la reprise
    // idempotente au lieu de charger le colis une seconde fois.
    const echec = bloc.slice(bloc.indexOf('} catch {'));
    expect(echec.slice(0, echec.indexOf('} finally'))).not.toContain('terminer(');
    expect(bloc).toContain("gestes.current.identifiant(colis.reference, action)");
    expect(bloc).not.toContain('crypto.randomUUID()');
  });
});
