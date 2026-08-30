'use client';

import { useRef, useState, type FormEvent } from 'react';

import type { CanalPaiement } from '@/lib/ops/payments';

/**
 * Enregistrer un encaissement.
 *
 * ## Ce que l'opérateur ne choisit pas
 *
 * Le collecteur est affiché mais figé : il vient de la correspondance
 * configurée une fois pour son compte, jamais de son nom d'affichage. Le
 * laisser modifiable rouvrirait précisément le problème d'imputation que cette
 * correspondance a fermé.
 *
 * ## L'identifiant de demande
 *
 * Tiré avant le premier envoi et conservé tant que la saisie ne change pas.
 * C'est ce qui fait qu'un réseau capricieux ne crée pas deux encaissements —
 * et, plus grave, deux écritures comptables.
 */
export function FormulairePaiement({
  canaux,
  collecteur,
  onAnnuler,
  soumettre,
}: {
  canaux: CanalPaiement[];
  collecteur: string;
  onAnnuler: () => void;
  soumettre: (
    demande: Record<string, unknown>,
  ) => Promise<{ ok: boolean; message?: string; code?: string }>;
}) {
  const premier = canaux[0];
  const [choix, setChoix] = useState(
    premier ? `${premier.code}|${premier.currency_code}` : '');
  const [montant, setMontant] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
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
    const [code, devise] = choix.split('|');
    const valeur = Number(montant.replace(',', '.'));

    if (!code || !devise) {
      setEtat({ nom: 'erreur', message: 'Choisissez un mode de paiement.' });
      return;
    }
    if (!Number.isFinite(valeur) || valeur <= 0) {
      setEtat({ nom: 'erreur', message: 'Le montant doit être supérieur à zéro.' });
      return;
    }
    if (date > new Date().toISOString().slice(0, 10)) {
      setEtat({ nom: 'erreur', message: 'La date ne peut pas être dans le futur.' });
      return;
    }

    requestUuid.current ??= crypto.randomUUID();
    setEtat({ nom: 'envoi' });
    try {
      const issue = await soumettre({
        request_uuid: requestUuid.current,
        amount: valeur,
        payment_date: date,
        payment_method: code,
        currency_code: devise,
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
    <form onSubmit={enregistrer} noValidate data-testid="formulaire-paiement">
      <h2 style={{ fontSize: '1.1rem', margin: '1rem 0 0.5rem' }}>
        ENREGISTRER UN PAIEMENT
      </h2>

      {etat.nom === 'erreur' ? (
        <p className="erreur" role="alert">{etat.message}</p>
      ) : null}

      <label htmlFor="mode-paiement">
        Mode de paiement
        <select
          id="mode-paiement"
          value={choix}
          onChange={(evenement) => changer(() => setChoix(evenement.target.value))}
        >
          {canaux.map((canal) => (
            <option
              key={`${canal.code}|${canal.currency_code}`}
              value={`${canal.code}|${canal.currency_code}`}
            >
              {canal.name} — {canal.currency_code}
            </option>
          ))}
        </select>
      </label>

      <label htmlFor="montant">
        Montant
        <input
          id="montant"
          type="number"
          inputMode="decimal"
          min="0.01"
          step="0.01"
          value={montant}
          onChange={(evenement) => changer(() => setMontant(evenement.target.value))}
        />
      </label>

      <label htmlFor="date-paiement">
        Date
        <input
          id="date-paiement"
          type="date"
          value={date}
          onChange={(evenement) => changer(() => setDate(evenement.target.value))}
        />
      </label>

      <p className="attenue" style={{ margin: '0 0 1rem' }}>
        Collecté par <strong data-testid="collecteur">{collecteur}</strong>
      </p>

      <button type="submit" disabled={etat.nom === 'envoi' || canaux.length === 0}>
        {etat.nom === 'envoi' ? 'Enregistrement…' : 'CONFIRMER L’ENCAISSEMENT'}
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
