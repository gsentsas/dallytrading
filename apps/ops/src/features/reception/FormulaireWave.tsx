'use client';

import { useRef, useState, type FormEvent } from 'react';

import type { ContexteWave } from '@/lib/ops/wave-payments';

export interface IssueWave {
  readonly ok: boolean;
  readonly message?: string;
  readonly code?: string;
}

/**
 * Encaisser par Wave.
 *
 * ## Ce que l'opérateur ne choisit pas
 *
 * Le moyen et le bénéficiaire, affichés mais figés. Ils viennent du serveur,
 * qui les impose : un transfert Wave arrive sur le compte de la caisse Dakar,
 * pas dans celui du logisticien qui le constate. Les afficher sans les rendre
 * modifiables évite qu'un écran promette une imputation que le serveur ne
 * fera pas.
 *
 * Le client non plus. Il vient du dossier, et l'écran ne fait que le rappeler.
 *
 * ## La référence Wave
 *
 * Facultative, à dessein. Un transfert reçu se voit dans l'application avant
 * que son numéro soit recopiable ; l'exiger bloquerait un encaissement qui a
 * bel et bien eu lieu. Fournie, elle ne peut pas servir deux fois.
 *
 * ## L'identifiant de demande
 *
 * Tiré avant le premier envoi et conservé tant que la saisie ne change pas.
 * Ici l'enjeu dépasse la ligne en double : un rejeu mal géré produirait une
 * seconde écriture comptable.
 */
export function FormulaireWave({
  contexte,
  onAnnuler,
  soumettre,
}: {
  contexte: ContexteWave;
  onAnnuler: () => void;
  soumettre: (demande: Record<string, unknown>) => Promise<IssueWave>;
}) {
  const aujourdhui = new Date().toISOString().slice(0, 10);
  // Le contexte est relu au serveur à chaque ouverture : la première
  // devise proposée est donc toujours à jour au montage.
  const premiere = contexte.currencies[0] ?? '';
  const [montant, setMontant] = useState('');
  const [devise, setDevise] = useState(premiere);
  const [referenceWave, setReferenceWave] = useState('');
  const [date, setDate] = useState(aujourdhui);
  const [note, setNote] = useState('');
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

    if (!Number.isFinite(valeur) || valeur <= 0) {
      setEtat({ nom: 'erreur', message: 'Le montant doit être supérieur à zéro.' });
      return;
    }
    if (!devise) {
      setEtat({ nom: 'erreur', message: 'Aucune devise Wave n’est configurée.' });
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
        amount: valeur,
        currency: devise,
        // Ni moyen ni bénéficiaire : le serveur les impose.
        wave_reference: referenceWave.trim() || null,
        paid_at: date,
        note: note.trim(),
      });
      if (!issue.ok) {
        if (issue.code === 'idempotency_conflict') requestUuid.current = null;
        setEtat({ nom: 'erreur', message: issue.message ?? 'Enregistrement impossible.' });
      }
    } catch {
      // L'identifiant est conservé : un nouvel appui rejoue la même demande.
      setEtat({ nom: 'erreur', message: 'Service momentanément indisponible.' });
    }
  }

  return (
    <form onSubmit={enregistrer} noValidate data-testid="formulaire-wave">
      <h2 style={{ fontSize: '1.1rem', margin: '1rem 0 0.5rem' }}>PAIEMENT PAR WAVE</h2>

      <p className="attenue" style={{ margin: '0 0 0.2rem' }}>
        BÉNÉFICIAIRE : <strong data-testid="beneficiaire-wave">
          {contexte.beneficiary.toUpperCase()}
        </strong>
      </p>
      <p className="attenue" style={{ margin: '0 0 0.2rem' }}>
        DOSSIER : <strong>{contexte.intake_reference}</strong>
      </p>
      <p className="attenue" style={{ margin: '0 0 1rem' }}>
        CLIENT : <strong data-testid="client-wave">{contexte.customer_name}</strong>
      </p>

      {etat.nom === 'erreur' ? (
        <p className="erreur" role="alert">{etat.message}</p>
      ) : null}

      <label htmlFor="montant-wave">
        Montant
        <input
          id="montant-wave"
          type="number"
          inputMode="decimal"
          min="0.01"
          step="0.01"
          value={montant}
          onChange={(e) => changer(() => setMontant(e.target.value))}
        />
      </label>

      <label htmlFor="devise-wave">
        Devise
        <select
          id="devise-wave"
          value={devise}
          onChange={(e) => changer(() => setDevise(e.target.value))}
        >
          {contexte.currencies.map((code) => (
            <option key={code} value={code}>{code}</option>
          ))}
        </select>
      </label>

      <label htmlFor="reference-wave">
        Référence Wave (facultative)
        <input
          id="reference-wave"
          type="text"
          maxLength={64}
          autoComplete="off"
          placeholder="Numéro lu dans Wave"
          value={referenceWave}
          onChange={(e) => changer(() => setReferenceWave(e.target.value))}
        />
      </label>

      <label htmlFor="date-wave">
        Date d’encaissement
        <input
          id="date-wave"
          type="date"
          max={aujourdhui}
          value={date}
          onChange={(e) => changer(() => setDate(e.target.value))}
        />
      </label>

      <label htmlFor="note-wave">
        Note (facultative)
        <input
          id="note-wave"
          type="text"
          maxLength={500}
          value={note}
          onChange={(e) => changer(() => setNote(e.target.value))}
        />
      </label>

      <button type="submit" disabled={etat.nom === 'envoi' || contexte.currencies.length === 0}>
        {etat.nom === 'envoi' ? 'Enregistrement…' : 'ENREGISTRER LE PAIEMENT WAVE'}
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
