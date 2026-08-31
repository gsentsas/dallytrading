import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  CONFIRMATION_ACTION,
  LIBELLES_ACTION,
  actionsProposables,
  corpsTransition,
  demandeConfirmation,
  gesteDemande,
  identifiantDeGeste,
  interpreterReponse,
  issueHorsLigne,
  issueReseau,
  type CibleEtat,
} from '@/features/reception/etat-vocabulaire';

/**
 * Les décisions de la carte d'état, prises hors de React pour être mesurables.
 *
 * Le projet n'embarque pas Testing Library : un clic ne se simule pas. Ces
 * décisions — quoi proposer, quoi confirmer, quel identifiant renvoyer, que
 * faire d'une réponse — sont donc extraites du composant et vérifiées une par
 * une. C'est plus sûr qu'un test de rendu : elles ne dépendent d'aucun DOM.
 */

describe('ce que l’écran propose', () => {
  it('F3 · propose la mise en préparation quand le serveur l’autorise', () => {
    expect(actionsProposables(['preparing'])).toEqual(['preparing']);
    expect(LIBELLES_ACTION.preparing).toBe('Mettre en préparation');
  });

  it('F4 · propose le passage à prêt quand le serveur l’autorise', () => {
    expect(actionsProposables(['ready'])).toEqual(['ready']);
    expect(LIBELLES_ACTION.ready).toBe('Marquer prêt à expédier');
  });

  it('F5 · ne propose rien quand la liste est vide', () => {
    expect(actionsProposables([])).toEqual([]);
  });

  it('F6 · n’invente jamais une étape que le serveur n’a pas renvoyée', () => {
    // Le cœur du contrat : l'écran ne connaît pas la machine à états. Un code
    // qu'il ne sait pas nommer ne devient pas un bouton.
    expect(actionsProposables(['departed'])).toEqual([]);
    expect(actionsProposables(['cancelled'])).toEqual([]);
    expect(actionsProposables(['delivered', 'in_transit', 'arrived'])).toEqual([]);
    expect(actionsProposables(['departed', 'preparing'])).toEqual(['preparing']);
    expect(Object.keys(LIBELLES_ACTION).sort()).toEqual(['preparing', 'ready']);
  });
});

describe('la confirmation', () => {
  it('F7 · « prêt à expédier » demande une confirmation', () => {
    expect(demandeConfirmation('ready')).toBeTruthy();
  });

  it('F17 · « mettre en préparation » demande aussi une confirmation', () => {
    // Mesuré : `preparing` porte un libellé client dans la politique de
    // publication. L'étape parle donc au client, et mérite un arrêt.
    expect(demandeConfirmation('preparing')).toBeTruthy();
  });

  it('F18 · le texte de préparation annonce la visibilité au suivi client', () => {
    expect(CONFIRMATION_ACTION.preparing).toContain('suivi client');
    expect(CONFIRMATION_ACTION.preparing).toContain('En préparation');
  });

  it('les deux étapes offertes au terrain demandent une confirmation', () => {
    for (const cible of Object.keys(LIBELLES_ACTION) as CibleEtat[]) {
      expect(demandeConfirmation(cible), cible).toBeTruthy();
    }
  });

  it('F8 · elle annonce la visibilité dans le suivi client', () => {
    expect(CONFIRMATION_ACTION.ready).toContain('suivi client');
  });

  it('F9 · elle annonce la fin de l’édition depuis Dally Ops', () => {
    expect(CONFIRMATION_ACTION.ready).toContain('ne pourront plus être modifiés');
  });

  it('F21 · ne promet aucun message envoyé au client', () => {
    // Aucun envoi n'est démontré par le code : l'annoncer serait un mensonge.
    // Les deux textes sont soumis à la même règle.
    for (const texte of Object.values(CONFIRMATION_ACTION)) {
      const minuscule = (texte ?? '').toLowerCase();
      for (const promesse of ['sms', 'e-mail', 'email', 'notification',
        'sera envoyé', 'recevra', 'prévenu', 'averti']) {
        expect(minuscule, promesse).not.toContain(promesse);
      }
    }
  });
});

describe('le corps envoyé', () => {
  it('F11 · porte exactement trois champs', () => {
    const corps = corpsTransition('11111111-1111-4111-8111-111111111111',
                                  'goods_received', 'preparing');
    expect(Object.keys(corps).sort()).toEqual([
      'expected_state', 'request_uuid', 'target_state']);
    expect(corps.expected_state).toBe('goods_received');
    expect(corps.target_state).toBe('preparing');
  });

  it('F16 · ne contient aucun identifiant interne', () => {
    const corps = JSON.stringify(
      corpsTransition('u', 'goods_received', 'ready'));
    // `"id"` avec son guillemet ouvrant : `request_uuid"` finit par `id"` et
    // ferait un faux positif.
    for (const interdit of ['shipment_id', 'partner_id', '"id"', 'sync_source_key']) {
      expect(corps).not.toContain(interdit);
    }
  });
});

describe('l’identifiant du geste', () => {
  it('F12 · un réessai réutilise le même identifiant', () => {
    let compteur = 0;
    const nouveau = () => `uuid-${(compteur += 1)}`;
    const premier = identifiantDeGeste(null, 'preparing', nouveau);
    const reessai = identifiantDeGeste(premier, 'preparing', nouveau);
    expect(reessai.uuid).toBe(premier.uuid);
    expect(compteur).toBe(1);
  });

  it('un geste différent tire un nouvel identifiant', () => {
    let compteur = 0;
    const nouveau = () => `uuid-${(compteur += 1)}`;
    const premier = identifiantDeGeste(null, 'preparing', nouveau);
    const suivant = identifiantDeGeste(premier, 'ready', nouveau);
    expect(suivant.uuid).not.toBe(premier.uuid);
    expect(compteur).toBe(2);
  });
});

describe('ce que l’écran fait d’une réponse', () => {
  it('un succès est un succès', () => {
    expect(interpreterReponse(true, { success: true })).toEqual({ issue: 'ok' });
  });

  it('F13 · un dossier périmé se rafraîchit, il ne se réessaie pas', () => {
    const issue = interpreterReponse(false, { code: 'state_changed', error: 'x' });
    expect(issue.issue).toBe('perime');
    expect(issue).toHaveProperty('message');
    expect((issue as { message: string }).message).toContain('actualisé');
  });

  it('un refus métier remonte le message du serveur', () => {
    const issue = interpreterReponse(
      false, { code: 'state_transition_blocked', error: 'Dossier incomplet.' });
    expect(issue).toEqual({ issue: 'refus', message: 'Dossier incomplet.' });
  });

  it('une coupure réseau est réessayable, une étape impossible ne l’est pas', () => {
    expect(issueReseau().issue).toBe('reessayable');
    expect(issueHorsLigne().message).toContain('Connexion requise');
    expect(interpreterReponse(false, { code: 'state_transition_blocked' }).issue)
      .toBe('refus');
  });
});

describe('la file hors connexion reste intacte', () => {
  const lire = (chemin: string) =>
    readFileSync(fileURLToPath(new URL(`../../${chemin}`, import.meta.url)), 'utf8');

  it('F14 · aucune transition n’entre dans la file', () => {
    // Les opérations mises en file sont des créations : leur condition ne se
    // périme pas. Une transition, si — un rejeu tardif serait refusé sans
    // recours pour l'opérateur.
    const types = lire('lib/offline/types.ts');
    for (const interdit of ['state_advance', 'intake_state', 'target_state']) {
      expect(types).not.toContain(interdit);
    }
    const carte = lire('features/reception/EtatDossier.tsx');
    expect(carte).not.toContain('@/lib/offline');
    expect(carte).not.toContain('enfiler');
  });
});

describe('le chemin vers le serveur', () => {
  it('F19 · un appui n’envoie jamais directement — il ouvre une confirmation', () => {
    // C'est ce qui rend « Annuler » incapable d'écrire : il n'existe aucun
    // chemin depuis l'appui vers le serveur qui ne passe par « Confirmer ».
    for (const cible of Object.keys(LIBELLES_ACTION) as CibleEtat[]) {
      expect(gesteDemande(cible).etape, cible).toBe('confirmer');
    }
  });

  it('F20 · la confirmation porte le texte, et une seule fois', () => {
    const geste = gesteDemande('preparing');
    expect(geste.etape).toBe('confirmer');
    expect((geste as { message: string }).message)
      .toBe(CONFIRMATION_ACTION.preparing);
  });
});
