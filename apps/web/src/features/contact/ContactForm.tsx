'use client';

/**
 * Contact form.
 *
 * Single-step on purpose: someone who wants to ask a question should not be walked
 * through five screens. The multi-step treatment is for the quote form, where the
 * questions genuinely depend on the service.
 *
 * The idempotency key is generated once on mount and reused on every retry, so a
 * double-click or a dropped connection cannot create two leads.
 */

import { useMemo, useState } from 'react';
import { CONTACT_SUBJECTS, contactFormSchema } from './contact-schema';

interface FormState {
  lastName: string;
  firstName: string;
  companyName: string;
  email: string;
  phone: string;
  whatsapp: string;
  city: string;
  subject: string;
  message: string;
  website: string;
}

const EMPTY: FormState = {
  lastName: '', firstName: '', companyName: '',
  email: '', phone: '', whatsapp: '', city: '',
  subject: 'other', message: '', website: '',
};

type Status = 'editing' | 'submitting' | 'sent' | 'error';

export function ContactForm({ initialSubject }: { initialSubject?: string }) {
  const requestUuid = useMemo(() => crypto.randomUUID(), []);

  const [form, setForm] = useState<FormState>(() =>
    initialSubject &&
    CONTACT_SUBJECTS.some((subject) => subject.value === initialSubject)
      ? { ...EMPTY, subject: initialSubject }
      : EMPTY,
  );
  const [status, setStatus] = useState<Status>('editing');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    setErrors((previous) => {
      if (!previous[key]) return previous;
      const next = { ...previous };
      delete next[key];
      return next;
    });
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus('submitting');
    setSubmitError(null);

    const payload = {
      requestUuid,
      lastName: form.lastName,
      firstName: form.firstName || undefined,
      companyName: form.companyName || undefined,
      email: form.email || undefined,
      phone: form.phone || undefined,
      whatsapp: form.whatsapp || undefined,
      city: form.city || undefined,
      subject: form.subject,
      message: form.message,
      sourceUrl: typeof window !== 'undefined' ? window.location.href : undefined,
      referrerUrl:
        typeof document !== 'undefined' && document.referrer
          ? document.referrer
          : undefined,
      website: form.website || undefined,
    };

    // Validate with the same schema the server uses, so the two can never disagree
    // about what is acceptable. The server remains the authority.
    const local = contactFormSchema.safeParse(payload);
    if (!local.success) {
      const fields: Record<string, string> = {};
      for (const issue of local.error.issues) {
        const field = issue.path.join('.') || 'form';
        fields[field] ??= issue.message;
      }
      setErrors(fields);
      setStatus('editing');
      return;
    }

    try {
      const response = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await response.json();

      if (!response.ok || !body.success) {
        if (body?.error?.fields) {
          setErrors(body.error.fields as Record<string, string>);
        }
        setSubmitError(
          body?.error?.message ??
            'Votre message n’a pas pu être envoyé. Merci de réessayer.',
        );
        setStatus('error');
        return;
      }

      setReference(body.data.reference);
      setStatus('sent');
    } catch {
      setSubmitError(
        'Connexion interrompue. Vérifiez votre réseau et réessayez : votre message ne sera pas envoyé deux fois.',
      );
      setStatus('error');
    }
  }

  if (status === 'sent' && reference) {
    return (
      <div
        className="rounded-xl border border-green-200 bg-green-50 p-6"
        role="status"
        aria-live="polite"
      >
        <h2 className="text-xl font-bold text-green-800">Message envoyé</h2>
        <p className="mt-3 text-navy-800">
          Merci. Votre message est arrivé à notre équipe et nous revenons vers vous
          dans les meilleurs délais.
        </p>
        <p className="mt-4 text-navy-800">
          Votre référence : <strong className="font-mono text-lg">{reference}</strong>
        </p>
        <p className="mt-2 text-sm text-mist-600">
          Conservez-la : elle identifie votre demande dans tous nos échanges.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <div className="grid gap-5 sm:grid-cols-2">
        <Field
          label="Nom" required value={form.lastName}
          onChange={(v) => update('lastName', v)} error={errors.lastName}
          autoComplete="family-name"
        />
        <Field
          label="Prénom" value={form.firstName}
          onChange={(v) => update('firstName', v)} error={errors.firstName}
          autoComplete="given-name"
        />
        <Field
          label="Société" value={form.companyName}
          onChange={(v) => update('companyName', v)} error={errors.companyName}
          autoComplete="organization"
        />
        <Field
          label="Ville" value={form.city}
          onChange={(v) => update('city', v)} error={errors.city}
          autoComplete="address-level2"
        />
        <Field
          label="E-mail" type="email" value={form.email}
          onChange={(v) => update('email', v)} error={errors.email}
          autoComplete="email"
        />
        <Field
          label="Téléphone" type="tel" value={form.phone}
          onChange={(v) => update('phone', v)} error={errors.phone}
          autoComplete="tel"
        />
        <Field
          label="WhatsApp" type="tel" value={form.whatsapp}
          onChange={(v) => update('whatsapp', v)} error={errors.whatsapp}
        />

        <div>
          <label htmlFor="contact-subject" className="block font-medium text-navy-800">
            Sujet
          </label>
          <select
            id="contact-subject"
            value={form.subject}
            onChange={(event) => update('subject', event.target.value)}
            className="mt-2 w-full rounded-lg border border-mist-300 bg-white p-3"
          >
            {CONTACT_SUBJECTS.map((subject) => (
              <option key={subject.value} value={subject.value}>
                {subject.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label htmlFor="contact-message" className="block font-medium text-navy-800">
          Votre message
          <span aria-hidden="true" className="text-red-700"> *</span>
        </label>
        <textarea
          id="contact-message"
          rows={6}
          required
          value={form.message}
          onChange={(event) => update('message', event.target.value)}
          aria-invalid={errors.message ? true : undefined}
          aria-describedby={errors.message ? 'contact-message-error' : undefined}
          placeholder="Décrivez votre besoin : nature de la marchandise, trajet, délai souhaité…"
          className={`mt-2 w-full rounded-lg border p-3 ${
            errors.message ? 'border-red-500' : 'border-mist-300'
          }`}
        />
        {errors.message && (
          <p id="contact-message-error" className="mt-1 text-sm text-red-700" role="alert">
            {errors.message}
          </p>
        )}
      </div>

      <p className="text-sm text-mist-600">
        Un e-mail ou un téléphone au minimum, pour que nous puissions vous répondre.
      </p>

      {/* Honeypot: off-screen, out of tab order, hidden from assistive tech. */}
      <div className="dally-honeypot" aria-hidden="true">
        <label htmlFor="contact-website">Site web</label>
        <input
          id="contact-website" name="website" type="text" tabIndex={-1}
          autoComplete="off" value={form.website}
          onChange={(event) => update('website', event.target.value)}
        />
      </div>

      {submitError && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800"
          role="alert"
        >
          {submitError}
        </div>
      )}

      <button
        type="submit"
        disabled={status === 'submitting'}
        className="rounded-lg bg-green-700 px-6 py-3 font-semibold text-white transition-colors hover:bg-green-800 disabled:opacity-60"
      >
        {status === 'submitting' ? 'Envoi en cours…' : 'Envoyer mon message'}
      </button>
    </form>
  );
}

function Field({
  label, value, onChange, type = 'text', required = false, error, autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  error?: string | undefined;
  autoComplete?: string;
}) {
  const id = `contact-${label.replace(/[^a-zA-Z]/g, '').toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="block font-medium text-navy-800">
        {label}
        {required && <span aria-hidden="true" className="text-red-700"> *</span>}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        required={required}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`mt-2 w-full rounded-lg border p-3 ${
          error ? 'border-red-500' : 'border-mist-300'
        }`}
      />
      {error && (
        <p id={`${id}-error`} className="mt-1 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
