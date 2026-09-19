'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import type { Transfer } from '@/lib/ops/transfers';

function libelleEtat(t: Transfer): string {
  if (t.state === 'received') return 'Réception confirmée';
  if (t.state === 'cancelled') return 'Annulé';
  return t.can_acknowledge ? 'À confirmer' : 'En attente - suivi back-office';
}

export function TransfertsCaisse({
  initial,
  options,
}: {
  initial: { transfers: Transfer[] };
  options: {
    from_actor: string;
    recipients: { actor: string }[];
    currencies: { code: string; name: string }[];
    payment_methods: { code: string; name: string }[];
  };
}) {
  const router = useRouter();
  const [form, setForm] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [to, setTo] = useState(options.recipients[0]?.actor ?? '');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState(options.currencies[0]?.code ?? 'XOF');
  const [method, setMethod] = useState(options.payment_methods[0]?.code ?? 'cash');
  const [reason, setReason] = useState('');

  async function submit() {
    setBusy(true);
    setMessage('');
    const body = {
      request_uuid: crypto.randomUUID(),
      to_actor: to,
      transfer_date: new Date().toISOString().slice(0, 10),
      amount: Number(amount.replace(/\s/g, '')),
      currency_code: currency,
      payment_method: method,
      reason,
      comment: '',
    };
    const r = await fetch('/api/cash-transfers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => null);
    setBusy(false);
    if (!r.ok || !j?.success) {
      setMessage(j?.error ?? 'Opération impossible.');
      return;
    }
    setMessage('✓ TRANSFERT ENREGISTRÉ');
    setConfirm(false);
    setForm(false);
    router.refresh();
  }

  async function ack(t: Transfer) {
    if (!t.can_acknowledge) return;
    const r = await fetch(
      `/api/cash-transfers/${encodeURIComponent(t.reference)}/acknowledge`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_uuid: crypto.randomUUID() }),
      },
    );
    const j = await r.json().catch(() => null);
    if (!r.ok || !j?.success) {
      setMessage(j?.error ?? 'Réception impossible.');
      return;
    }
    setMessage('✓ RÉCEPTION CONFIRMÉE');
    router.refresh();
  }

  const aRecevoir = initial.transfers.filter(
    (t) => t.direction === 'incoming' && t.state === 'pending_receipt' && t.can_acknowledge,
  );
  const recus = initial.transfers.filter(
    (t) => t.direction === 'incoming' && !t.can_acknowledge,
  );
  const envoyes = initial.transfers.filter((t) => t.direction === 'outgoing');

  return (
    <>
      <h2>TRANSFERTS CAISSE</h2>
      {message && <p className="succes" role="status">{message}</p>}
      <button type="button" onClick={() => setForm(true)}>+ NOUVEAU TRANSFERT</button>

      {form && (
        <section className="carte">
          <h3>NOUVEAU TRANSFERT</h3>
          <label>Remis par<input readOnly value={options.from_actor} /></label>
          <label>
            Reçu par
            <select value={to} onChange={(e) => setTo(e.target.value)}>
              {options.recipients.map((x) => <option key={x.actor}>{x.actor}</option>)}
            </select>
          </label>
          <label>Montant<input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
          <label>
            Devise
            <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
              {options.currencies.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
            </select>
          </label>
          <label>
            Mode
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              {options.payment_methods.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
            </select>
          </label>
          <label>Motif<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>

          {confirm ? (
            <>
              <p className="carte">VOUS REMETTEZ<br /><strong>{amount} {currency}</strong><br />À<br /><strong>{to.toUpperCase()}</strong></p>
              <button type="button" onClick={submit} disabled={busy}>CONFIRMER</button>
              <button className="secondaire" type="button" onClick={() => setConfirm(false)}>CORRIGER</button>
            </>
          ) : (
            <button type="button" disabled={!to || !amount || !reason} onClick={() => setConfirm(true)}>
              CONFIRMER LA REMISE
            </button>
          )}
          <button className="secondaire" type="button" onClick={() => setForm(false)}>ANNULER</button>
        </section>
      )}

      <h3>À RECEVOIR</h3>
      {aRecevoir.length === 0 ? <p className="attenue">Aucun transfert à confirmer.</p> : null}
      {aRecevoir.map((t) => (
        <section className="carte" key={t.reference}>
          <strong>{t.from_actor} vous remet</strong>
          <p>{t.amount} {t.currency_code} · {t.payment_method}</p>
          <button type="button" onClick={() => ack(t)}>J&apos;AI REÇU LES FONDS</button>
        </section>
      ))}

      <h3>TRANSFERTS REÇUS / HISTORIQUE</h3>
      {recus.length === 0 ? <p className="attenue">Aucun transfert reçu enregistré.</p> : null}
      {recus.map((t) => (
        <section className="carte" key={t.reference}>
          <strong>{t.amount} {t.currency_code} de {t.from_actor}</strong>
          <p>{t.transfer_date} · {t.payment_method || 'Mode non précisé'} · {libelleEtat(t)}</p>
          {t.reason ? <p className="attenue">{t.reason}</p> : null}
        </section>
      ))}

      <h3>MES TRANSFERTS ENVOYÉS</h3>
      {envoyes.map((t) => (
        <section className="carte" key={t.reference}>
          <strong>{t.amount} {t.currency_code} à {t.to_actor}</strong>
          <p>{libelleEtat(t)}</p>
        </section>
      ))}
    </>
  );
}
