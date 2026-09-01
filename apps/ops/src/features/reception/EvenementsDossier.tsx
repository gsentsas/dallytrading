'use client';

import {
  useCallback, useEffect, useRef, useState,
  type ChangeEvent, type FormEvent,
} from 'react';

import type { Evenement, EvenementsDossier as Charge } from '@/lib/ops/events';

import {
  LONGUEUR_NOTE,
  creerSuiviDeGeste,
  dateLisible,
  demandeValide,
  interpreterEnvoi,
  libelleSource,
  motifDIndisponibilite,
  type NatureProposable,
} from './evenements-vocabulaire';

/**
 * Les événements opérationnels du dossier.
 *
 * ## Pourquoi ce bloc n'est pas l'ACTIVITÉ
 *
 * ACTIVITÉ raconte ce que Dally Ops a fait — qui a saisi quoi, et quand. Ce
 * bloc-ci raconte ce qui est arrivé au colis. Les confondre ferait croire
 * qu'écrire un événement est une trace applicative de plus, alors que c'est
 * une donnée métier que le back-office lira.
 *
 * ## Ce que l'écran ne propose pas
 *
 * Aucune publication client, aucune notification, aucune localisation, aucune
 * date modifiable, aucun changement d'état. Ces champs n'existent pas dans le
 * contrat : les afficher grisés laisserait croire qu'ils viendront.
 *
 * ## Ce que l'écran ne décide pas
 *
 * `can_add` et la liste des natures — avec leur règle de note — viennent du
 * serveur. La règle est reproduite ici pour griser le bouton avant l'appui, pas
 * pour se substituer à lui.
 */
export function EvenementsDossier({
  reference,
  peutConsigner,
}: {
  reference: string;
  peutConsigner: boolean;
}) {
  const [donnees, setDonnees] = useState<Charge | null>(null);
  const [chargement, setChargement] = useState(true);
  const [ouvert, setOuvert] = useState(false);
  const [kind, setKind] = useState('');
  const [note, setNote] = useState('');
  const [etat, setEtat] = useState<
    { nom: 'saisie' } | { nom: 'envoi' } | { nom: 'erreur'; message: string }
  >({ nom: 'saisie' });

  const geste = useRef(creerSuiviDeGeste(() => crypto.randomUUID()));

  const recharger = useCallback(async () => {
    try {
      const reponse = await fetch(
        `/api/intakes/${encodeURIComponent(reference)}/events`,
        { cache: 'no-store' });
      const corps = await reponse.json().catch(() => null);
      if (reponse.ok && corps?.success === true) setDonnees(corps.data);
    } finally {
      setChargement(false);
    }
  }, [reference]);

  useEffect(() => { void recharger(); }, [recharger]);

  const natures: readonly NatureProposable[] = donnees?.kinds ?? [];
  const nature = natures.find((candidate) => candidate.kind === kind);
  const envoyable = demandeValide(nature, note);

  function changerNature(evenement: ChangeEvent<HTMLSelectElement>) {
    // Une autre nature, c'est une autre intention : le serveur la compare.
    geste.current.terminer();
    setKind(evenement.target.value);
    setEtat({ nom: 'saisie' });
  }

  function changerNote(evenement: ChangeEvent<HTMLTextAreaElement>) {
    geste.current.terminer();
    setNote(evenement.target.value);
    setEtat({ nom: 'saisie' });
  }

  function fermer() {
    geste.current.terminer();
    setOuvert(false);
    setKind('');
    setNote('');
    setEtat({ nom: 'saisie' });
  }

  async function envoyer(formulaire: FormEvent<HTMLFormElement>) {
    formulaire.preventDefault();
    if (!envoyable || !nature) {
      setEtat({ nom: 'erreur', message: motifDIndisponibilite(nature, note) });
      return;
    }

    const corps: Record<string, unknown> = {
      request_uuid: geste.current.identifiant(),
      kind: nature.kind,
    };
    const propre = note.trim();
    if (propre) corps.note = propre;

    setEtat({ nom: 'envoi' });
    try {
      const reponse = await fetch(
        `/api/intakes/${encodeURIComponent(reference)}/events`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(corps),
        });
      const charge = await reponse.json().catch(() => null);
      const issue = interpreterEnvoi(reponse.ok, charge);
      if (issue.issue === 'ok') {
        fermer();
        await recharger();
        return;
      }
      setEtat({ nom: 'erreur', message: issue.message });
    } catch {
      // L'identifiant est conservé : un nouvel appui rejoue le même geste et
      // ne consigne pas un second événement.
      setEtat({
        nom: 'erreur',
        message: 'Connexion interrompue. Vous pouvez réessayer le même envoi.',
      });
    }
  }

  if (!peutConsigner) return null;

  const evenements: readonly Evenement[] = donnees?.events ?? [];

  return (
    <section aria-labelledby="evenements-titre" data-testid="evenements-dossier">
      <h2 id="evenements-titre">ÉVÉNEMENTS</h2>
      <p className="attenue" style={{ margin: '0 0 1rem' }}>
        Ce qui est arrivé au colis. Ces notes restent internes.
      </p>

      {etat.nom === 'erreur' ? (
        <p className="erreur" role="alert">{etat.message}</p>
      ) : null}

      {chargement ? <p className="attenue">Chargement…</p> : null}

      {!chargement && evenements.length === 0 ? (
        <p className="attenue" data-testid="aucun-evenement">
          Aucun événement consigné pour ce dossier.
        </p>
      ) : null}

      {evenements.map((element, rang) => (
        <section
          className="carte"
          key={`${element.event_date}-${rang}`}
          data-testid="evenement"
        >
          <p style={{ margin: 0 }}>
            <strong data-testid="evenement-nature">
              {element.kind_label || element.description}
            </strong>
          </p>
          {element.note ? (
            <p style={{ margin: '0.3rem 0 0' }} data-testid="evenement-note">
              {element.note}
            </p>
          ) : null}
          <p className="attenue" style={{ margin: '0.3rem 0 0' }}>
            <span data-testid="evenement-date">
              {dateLisible(element.event_date)}
            </span>
            {' — '}
            <span data-testid="evenement-auteur">{element.recorded_by}</span>
            {' — '}
            <span data-testid="evenement-etat">{element.status_label}</span>
            {' — '}
            <span data-testid="evenement-source">
              {libelleSource(element.source)}
            </span>
          </p>
        </section>
      ))}

      {donnees?.can_add && !ouvert ? (
        <button
          type="button"
          onClick={() => setOuvert(true)}
          data-testid="ouvrir-evenement"
        >
          + AJOUTER UN ÉVÉNEMENT
        </button>
      ) : null}

      {donnees?.can_add && ouvert ? (
        <form onSubmit={envoyer} noValidate data-testid="formulaire-evenement">
          <label htmlFor="evenement-nature">
            Type d’événement
            <select
              id="evenement-nature"
              data-testid="choix-nature-evenement"
              value={kind}
              onChange={changerNature}
            >
              <option value="">Choisir…</option>
              {natures.map((candidate) => (
                <option key={candidate.kind} value={candidate.kind}>
                  {candidate.label}
                  {candidate.note_required ? ' (note requise)' : ''}
                </option>
              ))}
            </select>
          </label>

          <label htmlFor="evenement-note">
            Note{nature?.note_required ? ' (obligatoire)' : ' (facultative)'}
            <textarea
              id="evenement-note"
              data-testid="note-evenement"
              rows={3}
              maxLength={LONGUEUR_NOTE}
              value={note}
              onChange={changerNote}
            />
          </label>

          <button
            type="submit"
            disabled={etat.nom === 'envoi' || !envoyable}
            data-testid="envoyer-evenement"
          >
            {etat.nom === 'envoi' ? 'Enregistrement…' : 'ENREGISTRER L’ÉVÉNEMENT'}
          </button>
          <button
            type="button"
            className="secondaire"
            style={{ marginTop: '0.6rem' }}
            onClick={fermer}
          >
            ANNULER
          </button>
        </form>
      ) : null}

      {donnees && !donnees.can_add ? (
        <p className="attenue" data-testid="ajout-evenement-ferme">
          Ce dossier n’accepte plus d’événement.
        </p>
      ) : null}
    </section>
  );
}
