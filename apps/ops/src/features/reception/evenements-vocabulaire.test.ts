import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  LONGUEUR_NOTE,
  LONGUEUR_NOTE_MINIMALE,
  creerSuiviDeGeste,
  dateLisible,
  demandeValide,
  determinerAffichageEvenements,
  interpreterEnvoi,
  libelleSource,
  lireEvenements,
  motifDIndisponibilite,
} from '@/features/reception/evenements-vocabulaire';

const SOURCE = readFileSync(
  fileURLToPath(new URL('./EvenementsDossier.tsx', import.meta.url)), 'utf8');

const EXIGEANTE = { kind: 'anomaly', label: 'Anomalie constatée', note_required: true };
const SOUPLE = { kind: 'repacked', label: 'Colis reconditionné', note_required: false };

describe('la règle de note reproduit celle du serveur', () => {
  it('exige une note pour les natures qui n’ont aucun sens sans elle', () => {
    expect(demandeValide(EXIGEANTE, '')).toBe(false);
    expect(demandeValide(EXIGEANTE, '  ')).toBe(false);
    expect(demandeValide(EXIGEANTE, 'ab')).toBe(false);
    expect(demandeValide(EXIGEANTE, 'abc')).toBe(true);
  });

  it('laisse les autres passer sans note', () => {
    expect(demandeValide(SOUPLE, '')).toBe(true);
    expect(demandeValide(SOUPLE, 'Refait au scotch')).toBe(true);
  });

  it('refuse au-delà de la borne, dans les deux cas', () => {
    const trop = 'x'.repeat(LONGUEUR_NOTE + 1);
    expect(demandeValide(SOUPLE, trop)).toBe(false);
    expect(demandeValide(EXIGEANTE, trop)).toBe(false);
  });

  it('refuse tant qu’aucune nature n’est choisie', () => {
    expect(demandeValide(undefined, 'Une note pourtant complète')).toBe(false);
  });

  it('dit ce qui manque, plutôt que de laisser deviner', () => {
    expect(motifDIndisponibilite(undefined, '')).toContain('nature');
    expect(motifDIndisponibilite(EXIGEANTE, 'ab')).toContain('note');
    expect(motifDIndisponibilite(SOUPLE, 'x'.repeat(LONGUEUR_NOTE + 1)))
      .toContain(String(LONGUEUR_NOTE));
    expect(motifDIndisponibilite(SOUPLE, '')).toBe('');
  });

  it('le minimum distingue une note d’un doigt resté appuyé', () => {
    expect(LONGUEUR_NOTE_MINIMALE).toBe(3);
  });
});

describe('l’identifiant du geste', () => {
  function suivi() {
    let rang = 0;
    return creerSuiviDeGeste(() => `geste-${(rang += 1)}`);
  }

  it('une reprise réseau garde le même geste', () => {
    const geste = suivi();
    expect(geste.identifiant()).toBe('geste-1');
    expect(geste.identifiant()).toBe('geste-1');
  });

  it('une intention close en ouvre une neuve', () => {
    const geste = suivi();
    const avant = geste.identifiant();
    geste.terminer();
    expect(geste.identifiant()).not.toBe(avant);
  });

  it('le composant clôt le geste sur la nature, la note et l’annulation', () => {
    // Trois points de clôture, un seul point de tirage : c'est ce qui rend la
    // reprise idempotente sans jamais confondre deux intentions.
    for (const fonction of ['function changerNature(', 'function changerNote(',
                            'function fermer(']) {
      const bloc = SOURCE.slice(SOURCE.indexOf(fonction));
      expect(bloc.slice(0, bloc.indexOf('\n  }')), fonction)
        .toContain('geste.current.terminer()');
    }
    const envoyer = SOURCE.slice(SOURCE.indexOf('async function envoyer('));
    expect(envoyer).toContain('geste.current.identifiant()');
    expect(envoyer).not.toContain('crypto.randomUUID()');
  });
});

describe('ce que l’opérateur lit', () => {
  it('reprend le message du serveur, qui seul sait pourquoi il refuse', () => {
    expect(interpreterEnvoi(false, {
      success: false, error: 'Ce dossier n’accepte plus d’événement.',
    })).toEqual({ issue: 'refus', message: 'Ce dossier n’accepte plus d’événement.' });
  });

  it('garantit un message même quand le serveur n’en donne aucun', () => {
    const issue = interpreterEnvoi(false, null);
    expect(issue.issue).toBe('refus');
    expect(issue).toHaveProperty('message');
  });

  it('nomme l’origine en mots, jamais en code', () => {
    expect(libelleSource('ops')).toBe('Terrain');
    expect(libelleSource('backoffice')).toBe('Back-office');
  });

  it('la date se lit sans fuseau ni secondes', () => {
    expect(dateLisible('2026-09-01T09:05:00Z')).toMatch(
      /^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
    expect(dateLisible('pas-une-date')).toBe('');
  });
});

describe('une lecture qui échoue n’est pas un dossier vide', () => {
  const CHARGE = { events: [], can_add: true, kinds: [] };

  function affichage(issue: 'ok' | 'echec', ouvert = true) {
    return determinerAffichageEvenements({
      chargement: false,
      lectureEchouee: issue === 'echec',
      nombreEvenements: 0,
      canAdd: true,
      ouvert,
    });
  }

  it('rend les données quand le serveur a répondu', async () => {
    expect(await lireEvenements(
      async () => ({ ok: true, corps: { success: true, data: CHARGE } })))
      .toEqual({ issue: 'ok', donnees: CHARGE });
  });

  it.each([
    ['HTTP 503', async () => ({ ok: false, corps: null })],
    ['HTTP 200 avec success=false', async () => ({
      ok: true, corps: { success: false, error: 'Session expirée.' },
    })],
    ['exception réseau', async () => {
      throw new TypeError('Failed to fetch');
    }],
  ] as const)('%s affiche l’indisponibilité, jamais le vide ni le formulaire',
    async (_scenario, appeler) => {
      const resultat = await lireEvenements(appeler);
      expect(resultat).toEqual({ issue: 'echec' });
      expect(affichage(resultat.issue)).toMatchObject({
        indisponible: true,
        aucunEvenement: false,
        formulaire: false,
      });
    });

  it('un vrai succès vide affiche le vide, pas l’indisponibilité', async () => {
    const resultat = await lireEvenements(
      async () => ({ ok: true, corps: { success: true, data: CHARGE } }));
    expect(resultat).toEqual({ issue: 'ok', donnees: CHARGE });
    expect(affichage(resultat.issue)).toMatchObject({
      indisponible: false,
      aucunEvenement: true,
    });
  });

  it('refuse un corps illisible', async () => {
    expect(await lireEvenements(async () => ({ ok: true, corps: null })))
      .toEqual({ issue: 'echec' });
  });

  it('le composant expose les deux états sous leurs identifiants stables', () => {
    expect(SOURCE).toContain('data-testid="evenements-indisponibles"');
    expect(SOURCE).toContain('data-testid="aucun-evenement"');
    expect(SOURCE).toContain('data-testid="formulaire-evenement"');
  });
});

describe('le vocabulaire n’invente aucune nature', () => {
  it('la liste vient du serveur, elle n’est pas recopiée ici', () => {
    const vocabulaire = readFileSync(fileURLToPath(
      new URL('./evenements-vocabulaire.ts', import.meta.url)), 'utf8');
    for (const code of ['anomaly', 'damage_noted', 'customer_contacted',
                        'awaiting_customer', 'repacked', 'handover']) {
      expect(vocabulaire, code).not.toContain(`'${code}'`);
    }
    expect(SOURCE).toContain('donnees?.kinds');
  });
});
