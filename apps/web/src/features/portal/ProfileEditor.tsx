'use client';

import { useState, type FormEvent } from 'react';

import {
  portalProfileSchema,
  type PortalProfile,
  type PortalProfileUpdate,
} from '@/lib/portal/dto';
import { Card, Detail } from './ui';

const EDITABLE = ['name', 'phone', 'street', 'street2', 'zip', 'city'] as const;
type EditableField = (typeof EDITABLE)[number];
type Draft = Record<EditableField, string>;

function draftFrom(profile: PortalProfile): Draft {
  return {
    name: profile.name,
    phone: profile.phone ?? '',
    street: profile.street ?? '',
    street2: profile.street2 ?? '',
    zip: profile.zip ?? '',
    city: profile.city ?? '',
  };
}

const inputClass =
  'mt-1 w-full rounded-lg border border-mist-300 bg-white px-3 py-2 text-navy-900 outline-none transition focus:border-green-600 focus:ring-2 focus:ring-green-100 disabled:opacity-60';

export function ProfileEditor({
  initialProfile,
}: {
  readonly initialProfile: PortalProfile;
}) {
  const [profile, setProfile] = useState(initialProfile);
  const [draft, setDraft] = useState(() => draftFrom(initialProfile));
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  function startEditing() {
    setDraft(draftFrom(profile));
    setError('');
    setSuccess('');
    setEditing(true);
  }

  function cancel() {
    setDraft(draftFrom(profile));
    setError('');
    setEditing(false);
  }

  function change(field: EditableField, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setSuccess('');

    const changes: PortalProfileUpdate = {};
    for (const field of EDITABLE) {
      const value = draft[field].trim();
      const current = profile[field] ?? '';
      if (value !== current) changes[field] = value;
    }

    if (Object.keys(changes).length === 0) {
      setEditing(false);
      return;
    }

    setBusy(true);
    try {
      const response = await fetch('/api/portal/profile', {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
        cache: 'no-store',
      });
      const envelope = await response.json() as {
        success?: boolean;
        data?: unknown;
        error?: { message?: string };
      };

      if (!response.ok || !envelope.success) {
        setError(
          envelope.error?.message
            ?? 'La mise à jour a échoué. Merci de réessayer.',
        );
        return;
      }

      const confirmed = portalProfileSchema.safeParse(envelope.data);
      if (!confirmed.success) {
        setError('La réponse du service est invalide. Merci de réessayer.');
        return;
      }

      setProfile(confirmed.data);
      setDraft(draftFrom(confirmed.data));
      setEditing(false);
      setSuccess('Votre profil a été mis à jour.');
    } catch {
      setError('Le service est momentanément indisponible. Merci de réessayer.');
    } finally {
      setBusy(false);
    }
  }

  if (!editing) {
    return (
      <>
        {success && (
          <p
            role="status"
            className="mb-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900"
          >
            {success}
          </p>
        )}
        <Card>
          <dl className="grid gap-4 sm:grid-cols-2">
            <Detail label="Nom" value={profile.name} />
            <Detail label="Société" value={profile.company} />
            <Detail label="E-mail" value={profile.email} />
            <Detail label="Téléphone" value={profile.phone} />
            <Detail label="Adresse" value={profile.street} />
            <Detail label="Complément d’adresse" value={profile.street2} />
            <Detail label="Code postal" value={profile.zip} />
            <Detail label="Ville" value={profile.city} />
            <Detail label="Pays" value={profile.country} />
          </dl>

          <div className="mt-6 border-t border-mist-200 pt-5">
            <button
              type="button"
              onClick={startEditing}
              className="rounded-lg bg-navy-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-navy-800"
            >
              Modifier
            </button>
          </div>
        </Card>
        <p className="mt-4 text-sm text-mist-600">
          L’e-mail, la société et le pays restent gérés par DallyTrading.
        </p>
      </>
    );
  }

  return (
    <Card>
      <form onSubmit={save} noValidate>
        <div className="grid gap-5 sm:grid-cols-2">
          <label className="text-sm font-medium text-navy-800">
            Nom
            <input
              required
              maxLength={120}
              value={draft.name}
              onChange={(event) => change('name', event.target.value)}
              disabled={busy}
              className={inputClass}
              autoComplete="name"
            />
          </label>
          <label className="text-sm font-medium text-navy-800">
            Téléphone
            <input
              maxLength={64}
              value={draft.phone}
              onChange={(event) => change('phone', event.target.value)}
              disabled={busy}
              className={inputClass}
              autoComplete="tel"
              inputMode="tel"
            />
          </label>
          <label className="text-sm font-medium text-navy-800">
            Adresse
            <input
              maxLength={128}
              value={draft.street}
              onChange={(event) => change('street', event.target.value)}
              disabled={busy}
              className={inputClass}
              autoComplete="address-line1"
            />
          </label>
          <label className="text-sm font-medium text-navy-800">
            Complément d’adresse
            <input
              maxLength={128}
              value={draft.street2}
              onChange={(event) => change('street2', event.target.value)}
              disabled={busy}
              className={inputClass}
              autoComplete="address-line2"
            />
          </label>
          <label className="text-sm font-medium text-navy-800">
            Code postal
            <input
              maxLength={32}
              value={draft.zip}
              onChange={(event) => change('zip', event.target.value)}
              disabled={busy}
              className={inputClass}
              autoComplete="postal-code"
            />
          </label>
          <label className="text-sm font-medium text-navy-800">
            Ville
            <input
              maxLength={128}
              value={draft.city}
              onChange={(event) => change('city', event.target.value)}
              disabled={busy}
              className={inputClass}
              autoComplete="address-level2"
            />
          </label>
        </div>

        <dl className="mt-6 grid gap-4 border-t border-mist-200 pt-5 sm:grid-cols-3">
          <Detail label="Société (lecture seule)" value={profile.company} />
          <Detail label="E-mail (lecture seule)" value={profile.email} />
          <Detail label="Pays (lecture seule)" value={profile.country} />
        </dl>

        {error && (
          <p
            role="alert"
            className="mt-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          >
            {error}
          </p>
        )}

        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-green-700 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-green-800 disabled:opacity-60"
          >
            {busy ? 'Enregistrement…' : 'Enregistrer'}
          </button>
          <button
            type="button"
            onClick={cancel}
            disabled={busy}
            className="rounded-lg border border-mist-300 px-5 py-2.5 text-sm font-medium text-navy-800 transition hover:bg-mist-100 disabled:opacity-60"
          >
            Annuler
          </button>
        </div>
      </form>
    </Card>
  );
}
