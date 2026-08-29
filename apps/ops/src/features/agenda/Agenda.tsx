'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';

import { FormulaireClient } from '@/features/reception/FormulaireClient';
import { RechercheClient } from '@/features/reception/RechercheClient';
import type { Client } from '@/lib/ops/customers';
import type { Appointment, AppointmentDetail } from '@/lib/ops/appointments';
import type { Consolidation } from '@/lib/ops/consolidations';
import { RECEPTION_AGENDA_KEY } from '@/features/agenda/reception-context';

const KIND_LABELS = {
  dropoff: 'Dépôt colis', pickup: 'Collecte client', call: 'Appel',
  whatsapp: 'WhatsApp', other: 'Autre',
} as const;
const STATUS_LABELS = {
  scheduled: 'Prévu', present: 'Présent', absent: 'Absent', rescheduled: 'Reporté',
} as const;

type View = 'list' | 'find-customer' | 'create-customer' | 'form' | 'detail' | 'reschedule';
type Period = 'today' | 'week';

function localInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function periodRange(period: Period): { from: string; to: string } {
  const now = new Date();
  const from = new Date(now);
  from.setHours(0, 0, 0, 0);
  if (period === 'week') {
    const day = (from.getDay() + 6) % 7;
    from.setDate(from.getDate() - day);
  }
  const to = new Date(from);
  to.setDate(to.getDate() + (period === 'today' ? 1 : 7));
  return { from: from.toISOString(), to: to.toISOString() };
}

function displayDay(value: string): string {
  return new Intl.DateTimeFormat('fr-FR', {
    day: 'numeric', month: 'long', timeZone: undefined,
  }).format(new Date(value));
}

function displayTime(value: string): string {
  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value));
}

async function jsonRequest(path: string, init?: RequestInit) {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => null) as {
    success?: boolean; data?: unknown; error?: string;
  } | null;
  if (!response.ok || !body?.success) {
    throw new Error(body?.error ?? 'Opération impossible.');
  }
  return body.data;
}

export function Agenda() {
  const router = useRouter();
  const [view, setView] = useState<View>('list');
  const [period, setPeriod] = useState<Period>('today');
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [detail, setDetail] = useState<AppointmentDetail | null>(null);
  const [customer, setCustomer] = useState<Client | null>(null);
  const [consolidations, setConsolidations] = useState<Consolidation[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(10, 0, 0, 0);
  const [startLocal, setStartLocal] = useState(localInput(tomorrow));
  const [duration, setDuration] = useState('30');
  const [kind, setKind] = useState<keyof typeof KIND_LABELS>('dropoff');
  const [consolidation, setConsolidation] = useState('');
  const [location, setLocation] = useState('Dépôt Dakar');
  const [note, setNote] = useState('');

  const loadList = useCallback(async (selected: Period) => {
    setBusy(true);
    setError('');
    try {
      const range = periodRange(selected);
      const params = new URLSearchParams(range);
      const data = await jsonRequest(`/api/appointments?${params}`) as {
        appointments: Appointment[];
      };
      setAppointments(data.appointments);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Agenda indisponible.');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const task = window.setTimeout(() => void loadList(period), 0);
    return () => window.clearTimeout(task);
  }, [loadList, period]);

  async function openDetail(reference: string) {
    setBusy(true);
    setError('');
    try {
      const data = await jsonRequest(
        `/api/appointments/${encodeURIComponent(reference)}`,
      ) as AppointmentDetail;
      setDetail(data);
      setView('detail');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Rendez-vous indisponible.');
    } finally {
      setBusy(false);
    }
  }

  async function loadConsolidations() {
    if (consolidations.length) return;
    const data = await jsonRequest('/api/consolidations') as { consolidations: Consolidation[] };
    setConsolidations(data.consolidations);
  }

  function useCustomer(selected: Client) {
    setCustomer(selected);
    setView('form');
    void loadConsolidations().catch(() => setError('Impossible de charger les départs.'));
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!customer) return;
    const start = new Date(startLocal);
    const end = new Date(start.getTime() + Number(duration) * 60_000);
    if (Number.isNaN(start.getTime())) {
      setError('Choisissez une date et une heure.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const data = await jsonRequest('/api/appointments', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_uuid: crypto.randomUUID(), customer_reference: customer.reference,
          kind, start_at: start.toISOString(), end_at: end.toISOString(),
          consolidation_reference: consolidation || null,
          location: location.trim(), note: note.trim(),
        }),
      }) as { appointment: AppointmentDetail };
      setDetail(data.appointment);
      setView('detail');
      await loadList(period);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Création impossible.');
    } finally {
      setBusy(false);
    }
  }

  async function mark(action: 'present' | 'absent') {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      const data = await jsonRequest(
        `/api/appointments/${encodeURIComponent(detail.reference)}/${action}`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_uuid: crypto.randomUUID() }) },
      ) as { appointment: AppointmentDetail };
      setDetail(data.appointment);
      await loadList(period);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Action impossible.');
    } finally {
      setBusy(false);
    }
  }

  async function reschedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail) return;
    const start = new Date(startLocal);
    const end = new Date(start.getTime() + Number(duration) * 60_000);
    setBusy(true);
    setError('');
    try {
      const data = await jsonRequest(
        `/api/appointments/${encodeURIComponent(detail.reference)}/reschedule`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_uuid: crypto.randomUUID(),
            start_at: start.toISOString(), end_at: end.toISOString() }) },
      ) as { appointment: AppointmentDetail };
      setDetail(data.appointment);
      setView('detail');
      await loadList(period);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Report impossible.');
    } finally {
      setBusy(false);
    }
  }

  async function prepareReception() {
    if (!detail) return;
    setBusy(true);
    setError('');
    try {
      const data = await jsonRequest(
        `/api/appointments/${encodeURIComponent(detail.reference)}/prepare-reception`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ request_uuid: crypto.randomUUID() }) },
      );
      sessionStorage.setItem(RECEPTION_AGENDA_KEY, JSON.stringify(data));
      router.push('/reception/colis/preparee');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Préparation impossible.');
      setBusy(false);
    }
  }

  if (view === 'find-customer') {
    return <><button className="secondaire" onClick={() => setView('list')}>← Agenda</button>
      <h1>Nouveau rendez-vous</h1><h2>Identifier le client</h2>
      <RechercheClient onCustomer={useCustomer} onCreateRequested={() => setView('create-customer')} /></>;
  }
  if (view === 'create-customer') {
    return <><button className="secondaire" onClick={() => setView('find-customer')}>← Rechercher</button>
      <h1>Nouveau client</h1><FormulaireClient onCustomer={useCustomer} /></>;
  }
  if (view === 'form' && customer) {
    return <><button className="secondaire" onClick={() => setView('find-customer')}>← Changer de client</button>
      <h1>NOUVEAU RENDEZ-VOUS</h1><section className="carte"><strong>Client</strong><p>{customer.name}</p></section>
      {error ? <p className="erreur" role="alert">{error}</p> : null}
      <form onSubmit={create}>
        <label>Type<select aria-label="Type de rendez-vous" value={kind} onChange={(e) => setKind(e.target.value as keyof typeof KIND_LABELS)}>
          {Object.entries(KIND_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>Date et heure<input aria-label="Date et heure" type="datetime-local" value={startLocal} onChange={(e) => setStartLocal(e.target.value)} /></label>
        <label>Durée<select aria-label="Durée" value={duration} onChange={(e) => setDuration(e.target.value)}><option value="30">30 minutes</option><option value="60">1 heure</option></select></label>
        <label>Départ (facultatif)<select aria-label="Départ" value={consolidation} onChange={(e) => setConsolidation(e.target.value)}><option value="">Aucun départ</option>{consolidations.map((item) => <option key={item.reference} value={item.reference}>{item.reference}</option>)}</select></label>
        <label>Lieu<input aria-label="Lieu" value={location} onChange={(e) => setLocation(e.target.value)} /></label>
        <label>Note<textarea aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button disabled={busy || !location.trim()}>{busy ? 'Enregistrement…' : 'ENREGISTRER LE RENDEZ-VOUS'}</button>
      </form></>;
  }
  if (view === 'reschedule' && detail) {
    const proposed = new Date(startLocal);
    return <><button className="secondaire" onClick={() => setView('detail')}>← Annuler</button>
      <h1>REPORTER LE RENDEZ-VOUS</h1>
      <section className="carte"><p>Ancien : {displayDay(detail.start_at)} {displayTime(detail.start_at)}</p><p>Nouveau : {Number.isNaN(proposed.getTime()) ? '—' : `${displayDay(proposed.toISOString())} ${displayTime(proposed.toISOString())}`}</p></section>
      {error ? <p className="erreur" role="alert">{error}</p> : null}
      <form onSubmit={reschedule}><label>Nouvelle date et heure<input aria-label="Nouvelle date et heure" type="datetime-local" value={startLocal} onChange={(e) => setStartLocal(e.target.value)} /></label><label>Durée<select aria-label="Nouvelle durée" value={duration} onChange={(e) => setDuration(e.target.value)}><option value="30">30 minutes</option><option value="60">1 heure</option></select></label><button disabled={busy}>CONFIRMER LE REPORT</button></form></>;
  }
  if (view === 'detail' && detail) {
    const tel = detail.customer.phone.replace(/[^+\d]/g, '');
    const wa = (detail.customer.whatsapp || detail.customer.phone).replace(/\D/g, '');
    return <><button className="secondaire" onClick={() => setView('list')}>← Agenda</button>
      <h1>{detail.customer.name.toUpperCase()}</h1>
      <p>{displayDay(detail.start_at)}<br />{displayTime(detail.start_at)} → {displayTime(detail.end_at)}</p>
      <section className="carte"><strong>{KIND_LABELS[detail.kind]}</strong>{detail.consolidation_reference ? <p>Départ : <span className="reference">{detail.consolidation_reference}</span></p> : null}<p>{STATUS_LABELS[detail.status]}</p></section>
      <div className="actions-deux">{tel ? <a className="bouton-lien" href={`tel:${tel}`}>APPELER</a> : null}{wa ? <a className="bouton-lien" href={`https://wa.me/${wa}`} target="_blank" rel="noreferrer">WHATSAPP</a> : null}</div>
      {error ? <p className="erreur" role="alert">{error}</p> : null}
      {detail.status === 'scheduled' ? <><button disabled={busy} onClick={() => void mark('present')}>CLIENT PRÉSENT</button><button className="secondaire" disabled={busy} onClick={() => void mark('absent')}>CLIENT ABSENT</button><button className="secondaire" onClick={() => { setStartLocal(localInput(new Date(detail.start_at))); setView('reschedule'); }}>REPORTER</button></> : null}
      {detail.status === 'present' ? <><p className="succes">✓ CLIENT PRÉSENT</p><button disabled={busy} onClick={() => void prepareReception()}>RÉCEPTIONNER LE COLIS</button></> : null}
      {detail.status === 'absent' ? <><p className="alerte">ABSENT</p><button onClick={() => { const next = new Date(detail.start_at); next.setDate(next.getDate() + 1); setStartLocal(localInput(next)); setView('reschedule'); }}>REPORTER LE RENDEZ-VOUS</button></> : null}
      {detail.status === 'rescheduled' ? <p className="alerte">REPORTÉ</p> : null}</>;
  }

  return <><h1>AGENDA</h1><div className="actions-deux"><button className={period === 'today' ? undefined : 'secondaire'} onClick={() => setPeriod('today')}>AUJOURD&apos;HUI</button><button className={period === 'week' ? undefined : 'secondaire'} onClick={() => setPeriod('week')}>SEMAINE</button></div>
    {error ? <p className="erreur" role="alert">{error}</p> : null}
    {busy ? <p className="attenue">Chargement…</p> : appointments.length ? appointments.map((item) => <button type="button" className="carte carte-rdv" key={item.reference} onClick={() => void openDetail(item.reference)}><time>{displayTime(item.start_at)}</time><span><strong>{item.customer.name}</strong><small>{KIND_LABELS[item.kind]}{item.consolidation_reference ? ` · ${item.consolidation_reference}` : ''}<br />{STATUS_LABELS[item.status]}</small></span></button>) : <p className="attenue">Aucun rendez-vous sur cette période.</p>}
    <button type="button" onClick={() => { setCustomer(null); setView('find-customer'); }}>+ NOUVEAU RENDEZ-VOUS</button></>;
}
