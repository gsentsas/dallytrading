'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';

import { libelleEtat } from '@/features/recherche/vocabulaire';
import {
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
  type Geste,
} from '@/features/reception/etat-vocabulaire';

/**
 * L'état du dossier, et la seule étape suivante que le serveur autorise.
 *
 * ## Ce que cet écran ne sait pas
 *
 * La machine à états. Il n'a ni matrice, ni ordre des étapes, ni notion de ce
 * qui vient après : il affiche un bouton par code reçu dans
 * `allowed_transitions`, et rien quand la liste est vide. Un code qu'il ne
 * sait pas nommer n'affiche aucun bouton — mieux vaut ne rien proposer que
 * proposer au hasard.
 *
 * ## Pourquoi l'identifiant du geste survit aux tentatives
 *
 * Le réseau d'un entrepôt coupe. Réessayer doit renvoyer **le même** geste :
 * un nouvel identifiant ferait une seconde transition d'un doigt qui n'a
 * appuyé qu'une fois. L'identifiant n'est renouvelé qu'au geste suivant.
 *
 * ## Pourquoi rien n'entre dans la file hors ligne
 *
 * Les opérations mises en file sont des créations : leur condition ne se
 * périme pas. Une transition, si — le dossier peut avoir avancé entre-temps,
 * et un rejeu tardif serait refusé sans recours. Hors connexion, on le dit.
 */


type Etat =
  | { readonly phase: 'repos' }
  | { readonly phase: 'confirmation'; readonly cible: CibleEtat }
  | { readonly phase: 'envoi'; readonly cible: CibleEtat }
  | { readonly phase: 'erreur'; readonly cible: CibleEtat;
      readonly message: string; readonly reessayable: boolean };

export function EtatDossier({
  reference, state, allowedTransitions, peutAvancer,
}: {
  reference: string;
  state: string;
  allowedTransitions: readonly string[];
  peutAvancer: boolean;
}) {
  const router = useRouter();
  const [etat, setEtat] = useState<Etat>({ phase: 'repos' });
  // Un identifiant par geste, pas par tentative.
  const geste = useRef<Geste | null>(null);

  function identifiant(cible: CibleEtat): string {
    geste.current = identifiantDeGeste(
      geste.current, cible, () => crypto.randomUUID());
    return geste.current.uuid;
  }

  async function envoyer(cible: CibleEtat) {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      const hors = issueHorsLigne();
      setEtat({ phase: 'erreur', cible, reessayable: true, message: hors.message });
      return;
    }
    setEtat({ phase: 'envoi', cible });
    try {
      const reponse = await fetch(
        `/api/intakes/${encodeURIComponent(reference)}/state`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            corpsTransition(identifiant(cible), state, cible)),
        },
      );
      const corps = await reponse.json().catch(() => null);
      const issue = interpreterReponse(reponse.ok, corps);
      if (issue.issue === 'ok') {
        geste.current = null;
        setEtat({ phase: 'repos' });
        router.refresh();
        return;
      }
      if (issue.issue === 'perime') {
        // Le dossier a bougé : on ne force jamais, on recharge et on le dit.
        geste.current = null;
        setEtat({ phase: 'erreur', cible, reessayable: false, message: issue.message });
        router.refresh();
        return;
      }
      setEtat({ phase: 'erreur', cible, reessayable: false, message: issue.message });
    } catch {
      // Le réseau a lâché : la même tentative pourra repartir à l'identique.
      const reseau = issueReseau();
      setEtat({ phase: 'erreur', cible, reessayable: true, message: reseau.message });
    }
  }

  function demander(cible: CibleEtat) {
    // Le chemin vers le serveur ne s'ouvre que depuis « Confirmer ».
    if (gesteDemande(cible).etape === 'confirmer') {
      setEtat({ phase: 'confirmation', cible });
      return;
    }
    void envoyer(cible);
  }

  const proposables = actionsProposables(allowedTransitions);

  return (
    <section className="carte" aria-labelledby="etat-dossier-titre">
      <h2 id="etat-dossier-titre" style={{ margin: 0, fontSize: '0.85rem' }}>
        ÉTAT DU DOSSIER
      </h2>
      <p data-testid="etat-libelle" style={{ margin: '0.25rem 0 0', fontWeight: 600 }}>
        {libelleEtat(state)}
      </p>

      {etat.phase === 'confirmation' ? (
        <div data-testid="etat-confirmation" style={{ marginTop: '0.75rem' }}>
          <p className="attenue" style={{ margin: 0 }}>
            {demandeConfirmation(etat.cible)}
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
            <button
              type="button" className="secondaire"
              style={{ flex: '1 1 0', minWidth: 0, width: 'auto' }}
              onClick={() => setEtat({ phase: 'repos' })}
            >
              Annuler
            </button>
            <button
              type="button"
              style={{ flex: '1 1 0', minWidth: 0, width: 'auto' }}
              onClick={() => { void envoyer(etat.cible); }}
            >
              Confirmer
            </button>
          </div>
        </div>
      ) : null}

      {etat.phase !== 'confirmation' && peutAvancer && proposables.length > 0 ? (
        <div style={{ marginTop: '0.75rem' }}>
          {proposables.map((cible) => (
            <button
              key={cible}
              type="button"
              data-testid={`etat-action-${cible}`}
              disabled={etat.phase === 'envoi'}
              onClick={() => demander(cible)}
              style={{ marginTop: '0.5rem' }}
            >
              {etat.phase === 'envoi' && etat.cible === cible
                ? 'Enregistrement…' : LIBELLES_ACTION[cible]}
            </button>
          ))}
        </div>
      ) : null}

      {etat.phase === 'erreur' ? (
        <div aria-live="polite" style={{ marginTop: '0.75rem' }}>
          <p className="erreur" data-testid="etat-erreur">{etat.message}</p>
          {etat.reessayable ? (
            <button
              type="button" className="secondaire"
              onClick={() => { void envoyer(etat.cible); }}
            >
              Réessayer
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
