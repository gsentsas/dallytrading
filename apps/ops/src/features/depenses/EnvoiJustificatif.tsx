'use client';

import { useRef, useState, type ChangeEvent, type FormEvent } from 'react';

import type { DepenseLue } from '@/lib/ops/expenses';
import { TAILLE_MAXIMALE_JUSTIFICATIF } from '@/lib/ops/expenses-vocabulaire';

export interface IssueJustificatif {
  readonly ok: boolean;
  readonly message?: string;
  readonly code?: string;
}

/** Ce qu'un appareil photo de téléphone produit. */
const TYPES = 'image/jpeg,image/png,image/webp,image/heic,image/heif';

/**
 * Joindre la photo du ticket.
 *
 * ## Un geste séparé, et jamais bloquant
 *
 * La dépense est déjà enregistrée quand cet écran s'ouvre. C'est délibéré :
 * dans un entrepôt, l'envoi d'une image échoue bien plus souvent que celui de
 * trois lignes de texte, et une coupure au mauvais moment ne doit pas effacer
 * l'argent déjà sorti de la caisse. L'écran le dit à l'opérateur, pour qu'il
 * n'ait pas peur de fermer.
 *
 * ## Ce qui est vérifié ici, et ce qui ne l'est pas
 *
 * On refuse tout de suite ce qu'on sait déjà trop lourd : c'est une minute de
 * 4G épargnée. On ne prétend pas pour autant valider le fichier — le type
 * annoncé par le navigateur se choisit, les octets non. C'est le serveur qui
 * tranche, et lui seul.
 */
export function EnvoiJustificatif({
  depense,
  onTermine,
  onAnnuler,
  soumettre,
}: {
  depense: DepenseLue;
  onTermine: () => void;
  onAnnuler: () => void;
  soumettre: (fichier: File, requestUuid: string) => Promise<IssueJustificatif>;
}) {
  const [fichier, setFichier] = useState<File | null>(null);
  const [etat, setEtat] = useState<
    { nom: 'saisie' } | { nom: 'envoi' } | { nom: 'erreur'; message: string }
  >({ nom: 'saisie' });
  const requestUuid = useRef<string | null>(null);

  function choisir(evenement: ChangeEvent<HTMLInputElement>) {
    const choisi = evenement.target.files?.[0] ?? null;
    // Un autre fichier, c'est un autre envoi.
    requestUuid.current = null;
    if (choisi && choisi.size > TAILLE_MAXIMALE_JUSTIFICATIF) {
      setFichier(null);
      setEtat({
        nom: 'erreur',
        message: 'La photo dépasse 10 Mo. Reprenez-la en qualité réduite.',
      });
      return;
    }
    setFichier(choisi);
    setEtat({ nom: 'saisie' });
  }

  async function envoyer(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    if (!fichier) {
      setEtat({ nom: 'erreur', message: 'Choisissez ou prenez une photo.' });
      return;
    }

    requestUuid.current ??= crypto.randomUUID();
    setEtat({ nom: 'envoi' });
    try {
      const issue = await soumettre(fichier, requestUuid.current);
      if (issue.ok) {
        onTermine();
        return;
      }
      if (issue.code === 'idempotency_conflict') requestUuid.current = null;
      setEtat({ nom: 'erreur', message: issue.message ?? 'Envoi impossible.' });
    } catch {
      // L'identifiant est conservé : un nouvel appui rejoue le même envoi et
      // ne produit pas une seconde pièce.
      setEtat({ nom: 'erreur', message: 'Service momentanément indisponible.' });
    }
  }

  return (
    <form onSubmit={envoyer} noValidate data-testid="formulaire-justificatif">
      <h2 style={{ fontSize: '1.1rem', margin: '1rem 0 0.5rem' }}>
        PHOTO DU JUSTIFICATIF
      </h2>
      <p className="attenue" style={{ margin: '0 0 1rem' }}>
        {depense.category} — {depense.description}
      </p>

      {etat.nom === 'erreur' ? (
        <p className="erreur" role="alert">{etat.message}</p>
      ) : null}

      <label htmlFor="justificatif">
        Photo du ticket
        <input
          id="justificatif"
          type="file"
          accept={TYPES}
          capture="environment"
          onChange={choisir}
        />
      </label>

      <p className="attenue" style={{ margin: '0 0 1rem' }}>
        La dépense est déjà enregistrée. Si l’envoi échoue, elle reste
        enregistrée : la photo pourra être ajoutée plus tard.
      </p>

      <button type="submit" disabled={etat.nom === 'envoi' || fichier === null}>
        {etat.nom === 'envoi' ? 'Envoi…' : 'ENVOYER LA PHOTO'}
      </button>
      <button
        type="button"
        className="secondaire"
        style={{ marginTop: '0.6rem' }}
        onClick={onAnnuler}
      >
        PLUS TARD
      </button>
    </form>
  );
}
