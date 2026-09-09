'use client';

import { useRef, useState, type FormEvent } from 'react';

import { OpsCardIcon } from '@/features/shell/OpsCardIcon';

import type { CanalPaiement } from '@/lib/ops/payments';

export function FormulairePaiement({
  canaux,
  collecteur,
  dossierLabel,
  clientName,
  onAnnuler,
  soumettre,
}: {
  canaux: CanalPaiement[];
  collecteur: string;
  dossierLabel?: string;
  clientName?: string;
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
  const [, devise = ''] = choix.split('|');

  function changer(action: () => void) {
    action();
    requestUuid.current = null;
  }

  async function enregistrer(evenement: FormEvent<HTMLFormElement>) {
    evenement.preventDefault();
    const [code, currency] = choix.split('|');
    const valeur = Number(montant.replace(',', '.'));

    if (!code || !currency) {
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
      const demande = {
        request_uuid: requestUuid.current,
        amount: valeur,
        payment_date: date,
        payment_method: code,
        currency_code: currency,
      };
      let issue = await soumettre(demande);
      if (!issue.ok && issue.code === 'payment_already_recorded') {
        const confirme = window.confirm(
          (issue.message ?? 'Ce dossier contient déjà un encaissement.') +
          '\n\nVoulez-vous vraiment enregistrer un paiement supplémentaire ?',
        );
        if (!confirme) {
          setEtat({ nom: 'erreur', message: 'Aucun nouveau paiement n’a été enregistré.' });
          return;
        }
        issue = await soumettre({ ...demande, confirm_existing_payment: true });
      }
      if (!issue.ok) {
        if (issue.code === 'idempotency_conflict') requestUuid.current = null;
        setEtat({ nom: 'erreur', message: issue.message ?? 'Enregistrement impossible.' });
      }
    } catch {
      setEtat({ nom: 'erreur', message: 'Service momentanément indisponible.' });
    }
  }

  return (
    <form className="ops-payment-form" onSubmit={enregistrer} noValidate data-testid="formulaire-paiement">
      <div className="ops-payment-heading">
        <span className="ops-payment-heading-icon" aria-hidden="true"><OpsCardIcon name="encaissement" /></span>
        <div>
          <h2>Encaissement</h2>
          <p>Enregistrer un paiement reçu d’un client.</p>
        </div>
      </div>

      {etat.nom === 'erreur' ? <p className="erreur" role="alert">{etat.message}</p> : null}

      {dossierLabel ? (
        <section className="ops-payment-context">
          <span className="ops-payment-context-icon tone-blue" aria-hidden="true"><OpsCardIcon name="recherche" /></span>
          <div><small>Dossier</small><strong>{dossierLabel}</strong></div>
        </section>
      ) : null}

      {clientName ? (
        <section className="ops-payment-context">
          <span className="ops-payment-context-icon tone-green" aria-hidden="true"><OpsCardIcon name="supervision" /></span>
          <div><small>Client</small><strong>{clientName}</strong></div>
        </section>
      ) : null}

      <label className="ops-payment-card" htmlFor="montant">
        <span className="ops-payment-card-icon tone-green" aria-hidden="true"><OpsCardIcon name="depenses" /></span>
        <span className="ops-payment-field-copy">
          <strong>Montant <em>*</em></strong>
          <span className="ops-payment-input-row">
            <input
              id="montant"
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              placeholder="Saisir le montant"
              value={montant}
              onChange={(evenement) => changer(() => setMontant(evenement.target.value))}
            />
            <span className="ops-payment-currency">{devise || '—'}</span>
          </span>
          <small>Entrez le montant reçu dans la devise du canal choisi.</small>
        </span>
      </label>

      <label className="ops-payment-card" htmlFor="mode-paiement">
        <span className="ops-payment-card-icon tone-orange" aria-hidden="true"><OpsCardIcon name="encaissement" /></span>
        <span className="ops-payment-field-copy">
          <strong>Mode de paiement <em>*</em></strong>
          <select
            id="mode-paiement"
            value={choix}
            onChange={(evenement) => changer(() => setChoix(evenement.target.value))}
          >
            {canaux.map((canal) => (
              <option key={`${canal.code}|${canal.currency_code}`} value={`${canal.code}|${canal.currency_code}`}>
                {canal.name} — {canal.currency_code}
              </option>
            ))}
          </select>
          <small>Espèces, virement, mobile money, chèque, selon les canaux autorisés.</small>
        </span>
      </label>

      <label className="ops-payment-card" htmlFor="date-paiement">
        <span className="ops-payment-card-icon tone-purple" aria-hidden="true"><OpsCardIcon name="agenda" /></span>
        <span className="ops-payment-field-copy">
          <strong>Date de paiement <em>*</em></strong>
          <input
            id="date-paiement"
            type="date"
            value={date}
            onChange={(evenement) => changer(() => setDate(evenement.target.value))}
          />
          <small>Collecté par <b data-testid="collecteur">{collecteur}</b>.</small>
        </span>
      </label>

      <button className="ops-payment-submit" type="submit" disabled={etat.nom === 'envoi' || canaux.length === 0}>
        <span aria-hidden="true">✓</span>
        {etat.nom === 'envoi' ? 'Enregistrement…' : 'CONFIRMER L’ENCAISSEMENT'}
      </button>
      <button type="button" className="secondaire ops-payment-cancel" onClick={onAnnuler}>Annuler</button>
    </form>
  );
}
