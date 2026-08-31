'use client';

import { useEffect, useId, useRef, useState } from 'react';

import type { IntakeSearchItem } from '@/lib/ops/intake-search';
import { ResultatsRecherche } from './ResultatsRecherche';

/** Le temps qu'on laisse au pouce avant d'interroger le serveur. */
const ATTENTE_MS = 350;

/**
 * En deçà, on n'interroge pas.
 *
 * Le serveur refuse de toute façon — c'est lui qui décide, et lui seul. Ce
 * seuil évite d'aller chercher un refus connu d'avance, et de faire clignoter
 * un message d'erreur sous les doigts de l'opérateur.
 */
const LONGUEUR_MINIMALE = 2;

type Etat =
  | { readonly phase: 'repos' }
  | { readonly phase: 'chargement' }
  | { readonly phase: 'resultats'; readonly requete: string;
      readonly items: readonly IntakeSearchItem[]; readonly hasMore: boolean }
  | { readonly phase: 'erreur'; readonly requete: string; readonly message: string };

export function FormulaireRecherche() {
  const [saisie, setSaisie] = useState('');
  const [etat, setEtat] = useState<Etat>({ phase: 'repos' });
  const champ = useRef<HTMLInputElement>(null);
  const identifiant = useId();

  const requete = saisie.trim();
  const tropCourt = requete.length < LONGUEUR_MINIMALE;

  useEffect(() => {
    if (tropCourt) return undefined;

    const controleur = new AbortController();
    const minuteur = setTimeout(() => {
      setEtat({ phase: 'chargement' });
      fetch(`/api/intakes/search?q=${encodeURIComponent(requete)}`, {
        signal: controleur.signal,
      })
        .then(async (reponse) => {
          const corps = await reponse.json().catch(() => null);
          if (reponse.ok && corps?.success === true) {
            setEtat({
              phase: 'resultats',
              requete,
              items: corps.data.items ?? [],
              hasMore: corps.data.has_more === true,
            });
            return;
          }
          // Le message vient du serveur quand il en donne un : lui seul sait
          // s'il s'agit d'une recherche trop courte, d'un quota atteint ou
          // d'une panne.
          setEtat({
            phase: 'erreur',
            requete,
            message: typeof corps?.error === 'string'
              ? corps.error
              : 'Recherche momentanément indisponible.',
          });
        })
        .catch((erreur: unknown) => {
          if (erreur instanceof DOMException && erreur.name === 'AbortError') return;
          setEtat({ phase: 'erreur', requete, message: 'Vérifiez votre connexion.' });
        });
    }, ATTENTE_MS);

    return () => {
      clearTimeout(minuteur);
      controleur.abort();
    };
  }, [requete, tropCourt]);

  // L'affichage se **déduit** de la saisie plutôt que d'être stocké : une
  // réponse qui ne concerne plus ce qui est tapé ne doit jamais rester à
  // l'écran, et rien n'a besoin d'être remis à zéro pour cela.
  const affichage: Etat = tropCourt
    ? { phase: 'repos' }
    : ((etat.phase === 'resultats' || etat.phase === 'erreur')
        && etat.requete !== requete)
      ? { phase: 'chargement' }
      : etat;

  return (
    <>
      <label htmlFor={identifiant}>Nom, téléphone ou référence</label>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          id={identifiant}
          ref={champ}
          type="search"
          inputMode="search"
          autoComplete="off"
          autoFocus
          enterKeyHint="search"
          value={saisie}
          onChange={(evenement) => setSaisie(evenement.target.value)}
          placeholder="Mayram, 77 123 45 67, A012…"
          style={{ flex: 1 }}
        />
        <button
          type="button"
          className="secondaire"
          onClick={() => { setSaisie(''); champ.current?.focus(); }}
          disabled={saisie === ''}
        >
          Effacer
        </button>
      </div>

      <div aria-live="polite" style={{ marginTop: '1rem' }}>
        {affichage.phase === 'repos' ? (
          <p className="attenue">Tapez au moins deux caractères.</p>
        ) : null}
        {affichage.phase === 'chargement' ? (
          <p className="attenue" data-test="recherche-chargement">Recherche…</p>
        ) : null}
        {affichage.phase === 'erreur' ? (
          <p className="erreur" data-test="recherche-erreur">{affichage.message}</p>
        ) : null}
        {affichage.phase === 'resultats' ? (
          <ResultatsRecherche items={affichage.items} hasMore={affichage.hasMore} />
        ) : null}
      </div>
    </>
  );
}
