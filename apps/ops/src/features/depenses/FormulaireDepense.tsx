'use client';

import { useRef, useState, type FormEvent } from 'react';

import { LIBELLES_MODE, MODES_PAIEMENT } from '@/lib/ops/expenses-vocabulaire';

export interface IssueDepense {
  readonly ok: boolean;
  readonly message?: string;
  readonly code?: string;
}

/** Les devises dans lesquelles la caisse de terrain paie réellement. */
const DEVISES = ['XOF', 'EUR'] as const;

/**
 * Déclarer une dépense engagée sur un départ.
 *
 * ## Ce que l'opérateur ne choisit pas
 *
 * Le payeur, affiché mais figé : il vient de la correspondance de caisse
 * configurée pour son compte, jamais de son nom d'affichage. Le rendre
 * modifiable permettrait d'imputer sa propre dépense à un collègue.
 *
 * L'état non plus. Toute dépense saisie ici arrive « à vérifier » côté
 * back-office : le terrain déclare, il ne valide pas.
 *
 * ## L'identifiant de demande
 *
 * Tiré avant le premier envoi et conservé tant que la saisie ne change pas.
 * C'est ce qui fait qu'un réseau capricieux n'enregistre pas deux fois la même
 * sortie de caisse.
 */
export function FormulaireDepense({
  depart,
  payeur,
  onAnnuler,
  soumettre,
}: {
  depart: string;
  payeur: string;
  onAnnuler: () => void;
  soumettre: (demande: Record<string, unknown>) => Promise<IssueDepense>;
}) {
  const aujourdhui = new Date().toISOString().slice(0, 10);
  const [categorie, setCategorie] = useState('');
  const [description, setDescription] = useState('');
  const [beneficiaire, setBeneficiaire] = useState('');
  const [montant, setMontant] = useState('');
  const [devise, setDevise] = useState<string>('XOF');
  const [mode, setMode] = useState<string>('cash');
  const [date, setDate] = useState(aujourdhui);
  const [commentaire, setCommentaire] = useState('');
  const [etat, setEtat] = useState<
    { nom: 'saisie' } | { nom: 'envoi' } | { nom: 'erreur'; message: string }
  >({ nom: 'saisie' });
  const requestUuid = useRef<string | null>(null);

  function changer(action: () => void) {
    action();
    // La saisie a changé : ce n'est plus la même demande.
    requestUuid.current = null;
  }

  async function enregistrer(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    const valeur = Number(montant.replace(',', '.'));

    if (!categorie.trim()) {
      setEtat({ nom: 'erreur', message: 'Indiquez la nature de la dépense.' });
      return;
    }
    if (!description.trim()) {
      setEtat({ nom: 'erreur', message: 'Décrivez la dépense en quelques mots.' });
      return;
    }
    if (!Number.isFinite(valeur) || valeur <= 0) {
      setEtat({ nom: 'erreur', message: 'Le montant doit être supérieur à zéro.' });
      return;
    }
    if (date > aujourdhui) {
      setEtat({ nom: 'erreur', message: 'La date ne peut pas être dans le futur.' });
      return;
    }

    requestUuid.current ??= crypto.randomUUID();
    setEtat({ nom: 'envoi' });
    try {
      const issue = await soumettre({
        request_uuid: requestUuid.current,
        consolidation_reference: depart,
        expense_date: date,
        category: categorie.trim(),
        description: description.trim(),
        beneficiary: beneficiaire.trim(),
        amount: valeur,
        currency_code: devise,
        payment_method: mode,
        comment: commentaire.trim(),
      });
      if (!issue.ok) {
        // Une demande refusée pour cause d'informations différentes ne doit
        // pas être rejouée telle quelle : on repart d'un identifiant neuf.
        if (issue.code === 'idempotency_conflict') requestUuid.current = null;
        setEtat({ nom: 'erreur', message: issue.message ?? 'Enregistrement impossible.' });
      }
    } catch {
      // L'identifiant est conservé : un nouvel appui rejoue la même demande.
      setEtat({ nom: 'erreur', message: 'Service momentanément indisponible.' });
    }
  }

  return (
    <form onSubmit={enregistrer} noValidate data-testid="formulaire-depense">
      <h2 style={{ fontSize: '1.1rem', margin: '1rem 0 0.5rem' }}>DÉCLARER UNE DÉPENSE</h2>

      {etat.nom === 'erreur' ? (
        <p className="erreur" role="alert">{etat.message}</p>
      ) : null}

      <label htmlFor="categorie">
        Nature
        <input
          id="categorie"
          type="text"
          maxLength={200}
          placeholder="Manutention, carburant, douane…"
          value={categorie}
          onChange={(e) => changer(() => setCategorie(e.target.value))}
        />
      </label>

      <label htmlFor="description">
        Description
        <input
          id="description"
          type="text"
          maxLength={500}
          value={description}
          onChange={(e) => changer(() => setDescription(e.target.value))}
        />
      </label>

      <label htmlFor="beneficiaire">
        Bénéficiaire (facultatif)
        <input
          id="beneficiaire"
          type="text"
          maxLength={200}
          value={beneficiaire}
          onChange={(e) => changer(() => setBeneficiaire(e.target.value))}
        />
      </label>

      <label htmlFor="montant-depense">
        Montant
        <input
          id="montant-depense"
          type="number"
          inputMode="decimal"
          min="0.01"
          step="0.01"
          value={montant}
          onChange={(e) => changer(() => setMontant(e.target.value))}
        />
      </label>

      <label htmlFor="devise-depense">
        Devise
        <select
          id="devise-depense"
          value={devise}
          onChange={(e) => changer(() => setDevise(e.target.value))}
        >
          {DEVISES.map((code) => (
            <option key={code} value={code}>{code}</option>
          ))}
        </select>
      </label>

      <label htmlFor="mode-depense">
        Payé par
        <select
          id="mode-depense"
          value={mode}
          onChange={(e) => changer(() => setMode(e.target.value))}
        >
          {MODES_PAIEMENT.map((code) => (
            <option key={code} value={code}>{LIBELLES_MODE[code]}</option>
          ))}
        </select>
      </label>

      <label htmlFor="date-depense">
        Date
        <input
          id="date-depense"
          type="date"
          max={aujourdhui}
          value={date}
          onChange={(e) => changer(() => setDate(e.target.value))}
        />
      </label>

      <label htmlFor="commentaire-depense">
        Commentaire (facultatif)
        <input
          id="commentaire-depense"
          type="text"
          maxLength={2000}
          value={commentaire}
          onChange={(e) => changer(() => setCommentaire(e.target.value))}
        />
      </label>

      <p className="attenue" style={{ margin: '0 0 1rem' }}>
        Sortie de caisse de <strong data-testid="payeur">{payeur}</strong>
      </p>

      <button type="submit" disabled={etat.nom === 'envoi'}>
        {etat.nom === 'envoi' ? 'Enregistrement…' : 'ENREGISTRER LA DÉPENSE'}
      </button>
      <button
        type="button"
        className="secondaire"
        style={{ marginTop: '0.6rem' }}
        onClick={onAnnuler}
      >
        ANNULER
      </button>
    </form>
  );
}
