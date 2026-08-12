'use client';

/**
 * Multi-step quote form (§36, §79).
 *
 * Design notes:
 *
 * * **The idempotency key is generated once**, when the form mounts, and reused on
 *   every retry. That is what makes a double-click or a flaky connection safe: the
 *   server recognises the second attempt as the same submission (§41).
 * * **Steps adapt to the service.** A sourcing prospect is never asked for a port
 *   of loading — irrelevant questions are how a form gets abandoned.
 * * **Client validation is convenience only.** The same zod schema runs on the
 *   server, which is the authority; this copy exists to give immediate feedback.
 * * **Errors are announced.** Messages carry `role="alert"` and inputs are wired
 *   with `aria-invalid` / `aria-describedby`, so a screen-reader user learns what
 *   went wrong instead of silently failing to submit (§53).
 */

import { useMemo, useState } from 'react';
import {
  QUOTE_SERVICES,
  STEP_LABELS,
  findService,
  stepsForService,
  type QuoteStepId,
} from './services';
import { quoteFormSchema } from './schema';

interface FormState {
  serviceCode: string;
  originCountry: string;
  originCity: string;
  destinationCountry: string;
  destinationCity: string;
  goods: string;
  weight: string;
  volume: string;
  packages: string;
  firstName: string;
  lastName: string;
  companyName: string;
  email: string;
  phone: string;
  whatsapp: string;
  city: string;
  countryCode: string;
  message: string;
  /** Honeypot. Hidden from users; a value here means an automated submission. */
  website: string;
}

const EMPTY: FormState = {
  serviceCode: '',
  originCountry: '', originCity: '',
  destinationCountry: '', destinationCity: '',
  goods: '', weight: '', volume: '', packages: '',
  firstName: '', lastName: '', companyName: '',
  email: '', phone: '', whatsapp: '',
  city: '', countryCode: '', message: '',
  website: '',
};

type Status = 'editing' | 'submitting' | 'sent' | 'error';

export function QuoteForm() {
  // Generated once per mounted form, not per attempt. Regenerating it on retry
  // would defeat idempotency and create a duplicate lead.
  const requestUuid = useMemo(() => crypto.randomUUID(), []);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [stepIndex, setStepIndex] = useState(0);
  const [status, setStatus] = useState<Status>('editing');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const steps = useMemo(
    () => stepsForService(form.serviceCode || null),
    [form.serviceCode],
  );
  const currentStep: QuoteStepId = steps[stepIndex] ?? 'service';
  const service = findService(form.serviceCode);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    // Clear the message for a field as soon as the user edits it: keeping a stale
    // error next to a corrected field is confusing.
    setErrors((previous) => {
      if (!previous[key]) return previous;
      const next = { ...previous };
      delete next[key];
      return next;
    });
  }

  /** Validate only the fields belonging to the current step. */
  function validateStep(): boolean {
    const stepErrors: Record<string, string> = {};

    if (currentStep === 'service' && !form.serviceCode) {
      stepErrors.serviceCode = 'Veuillez sélectionner un service.';
    }

    if (currentStep === 'contact') {
      if (!form.lastName.trim()) {
        stepErrors.lastName = 'Le nom est obligatoire.';
      }
      if (!form.email.trim() && !form.phone.trim()) {
        stepErrors.email = 'Indiquez au moins un e-mail ou un téléphone.';
      }
      // Reuse the shared schema for the email shape, so the client and the server
      // never disagree about what a valid address looks like.
      if (form.email.trim()) {
        const probe = quoteFormSchema.safeParse({
          requestUuid,
          serviceCode: form.serviceCode || 'other',
          lastName: form.lastName || 'x',
          email: form.email,
        });
        if (!probe.success) {
          const emailIssue = probe.error.issues.find((issue) =>
            issue.path.includes('email'),
          );
          if (emailIssue) {
            stepErrors.email = emailIssue.message;
          }
        }
      }
    }

    setErrors(stepErrors);
    return Object.keys(stepErrors).length === 0;
  }

  function goNext() {
    if (!validateStep()) return;
    setStepIndex((index) => Math.min(index + 1, steps.length - 1));
  }

  function goBack() {
    setErrors({});
    setStepIndex((index) => Math.max(index - 1, 0));
  }

  async function submit() {
    if (!validateStep()) return;

    setStatus('submitting');
    setSubmitError(null);

    // Route and cargo answers are folded into the message: they are freight
    // details a human reads, not structured lead fields. Once a shipment is
    // created from the lead they are captured properly on dally.shipment.
    const details: string[] = [];
    if (service?.requiresRoute) {
      if (form.originCity || form.originCountry) {
        details.push(`Origine : ${[form.originCity, form.originCountry].filter(Boolean).join(', ')}`);
      }
      if (form.destinationCity || form.destinationCountry) {
        details.push(`Destination : ${[form.destinationCity, form.destinationCountry].filter(Boolean).join(', ')}`);
      }
    }
    if (service?.requiresCargo) {
      if (form.goods) details.push(`Marchandise : ${form.goods}`);
      if (form.weight) details.push(`Poids : ${form.weight} kg`);
      if (form.volume) details.push(`Volume : ${form.volume} m³`);
      if (form.packages) details.push(`Colis : ${form.packages}`);
    }
    if (form.message) details.push(`Message : ${form.message}`);

    const payload = {
      requestUuid,
      serviceCode: form.serviceCode,
      firstName: form.firstName || undefined,
      lastName: form.lastName,
      companyName: form.companyName || undefined,
      email: form.email || undefined,
      phone: form.phone || undefined,
      whatsapp: form.whatsapp || undefined,
      city: form.city || undefined,
      countryCode: form.countryCode || undefined,
      message: details.join('\n') || undefined,
      sourceUrl: typeof window !== 'undefined' ? window.location.href : undefined,
      website: form.website || undefined,
    };

    try {
      const response = await fetch('/api/leads', {
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
            'Votre demande n’a pas pu être envoyée. Merci de réessayer.',
        );
        setStatus('error');
        return;
      }

      setReference(body.data.reference);
      setStatus('sent');
    } catch {
      // Network failure. The same requestUuid is kept, so pressing "réessayer"
      // cannot create a second lead if the first call in fact reached the server.
      setSubmitError(
        'Connexion interrompue. Vérifiez votre réseau et réessayez : votre demande ne sera pas envoyée deux fois.',
      );
      setStatus('error');
    }
  }

  // ─── Confirmation ─────────────────────────────────────────────────
  if (status === 'sent' && reference) {
    return (
      <div
        className="rounded-xl border border-green-200 bg-green-50 p-6"
        role="status"
        aria-live="polite"
      >
        <h2 className="text-xl font-bold text-green-700">Demande enregistrée</h2>
        <p className="mt-3 text-navy-800">
          Merci. Votre demande a bien été transmise à notre équipe.
        </p>
        <p className="mt-4 text-navy-800">
          Votre référence :{' '}
          <strong className="font-mono text-lg">{reference}</strong>
        </p>
        <p className="mt-2 text-sm text-mist-600">
          Conservez-la : elle identifie votre demande dans tous nos échanges.
        </p>
      </div>
    );
  }

  const isLastStep = stepIndex === steps.length - 1;

  return (
    <div>
      {/* Progress. aria-hidden because the same information is announced in the
          step heading below — reading it twice is noise for a screen reader. */}
      <ol className="mb-8 flex flex-wrap gap-2" aria-hidden="true">
        {steps.map((step, index) => (
          <li
            key={step}
            className={`rounded-full px-3 py-1 text-sm ${
              index === stepIndex
                ? 'bg-navy-700 text-white'
                : index < stepIndex
                  ? 'bg-green-100 text-green-700'
                  : 'bg-mist-100 text-mist-600'
            }`}
          >
            {index + 1}. {STEP_LABELS[step]}
          </li>
        ))}
      </ol>

      <h2 className="text-xl font-bold text-navy-800">
        Étape {stepIndex + 1} sur {steps.length} — {STEP_LABELS[currentStep]}
      </h2>

      <div className="mt-6 space-y-5">
        {currentStep === 'service' && (
          <fieldset>
            <legend className="font-medium text-navy-800">
              Quel service vous intéresse ?
            </legend>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {QUOTE_SERVICES.map((option) => (
                <label
                  key={option.code}
                  className={`cursor-pointer rounded-lg border p-4 ${
                    form.serviceCode === option.code
                      ? 'border-green-500 bg-green-50'
                      : 'border-mist-200 bg-white hover:border-navy-300'
                  }`}
                >
                  <input
                    type="radio"
                    name="serviceCode"
                    value={option.code}
                    checked={form.serviceCode === option.code}
                    onChange={() => update('serviceCode', option.code)}
                    className="sr-only"
                  />
                  <span className="block font-medium text-navy-700">
                    {option.label}
                  </span>
                  <span className="mt-1 block text-sm text-mist-600">
                    {option.description}
                  </span>
                </label>
              ))}
            </div>
            {errors.serviceCode && (
              <p className="mt-3 text-sm text-red-700" role="alert">
                {errors.serviceCode}
              </p>
            )}
          </fieldset>
        )}

        {currentStep === 'route' && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Pays d’origine" value={form.originCountry}
                   onChange={(v) => update('originCountry', v)} />
            <Field label="Ville d’origine" value={form.originCity}
                   onChange={(v) => update('originCity', v)} />
            <Field label="Pays de destination" value={form.destinationCountry}
                   onChange={(v) => update('destinationCountry', v)} />
            <Field label="Ville de destination" value={form.destinationCity}
                   onChange={(v) => update('destinationCity', v)} />
          </div>
        )}

        {currentStep === 'cargo' && (
          <div className="space-y-5">
            <Field label="Nature de la marchandise" value={form.goods}
                   onChange={(v) => update('goods', v)}
                   placeholder="Ex. pièces automobiles, textile, denrées" />
            <div className="grid gap-5 sm:grid-cols-3">
              <Field label="Poids (kg)" value={form.weight} type="number"
                     onChange={(v) => update('weight', v)} />
              <Field label="Volume (m³)" value={form.volume} type="number"
                     onChange={(v) => update('volume', v)} />
              <Field label="Nombre de colis" value={form.packages} type="number"
                     onChange={(v) => update('packages', v)} />
            </div>
          </div>
        )}

        {currentStep === 'contact' && (
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Nom" value={form.lastName} required
                   onChange={(v) => update('lastName', v)} error={errors.lastName} />
            <Field label="Prénom" value={form.firstName}
                   onChange={(v) => update('firstName', v)} />
            <Field label="Société" value={form.companyName}
                   onChange={(v) => update('companyName', v)} />
            <Field label="Ville" value={form.city}
                   onChange={(v) => update('city', v)} />
            <Field label="E-mail" value={form.email} type="email"
                   onChange={(v) => update('email', v)} error={errors.email} />
            <Field label="Téléphone" value={form.phone} type="tel"
                   onChange={(v) => update('phone', v)} error={errors.phone} />
            <Field label="WhatsApp" value={form.whatsapp} type="tel"
                   onChange={(v) => update('whatsapp', v)} />
            <div className="sm:col-span-2">
              <label className="block font-medium text-navy-800" htmlFor="message">
                Précisions
              </label>
              <textarea
                id="message"
                rows={4}
                value={form.message}
                onChange={(event) => update('message', event.target.value)}
                className="mt-2 w-full rounded-lg border border-mist-300 p-3"
              />
            </div>
            <p className="text-sm text-mist-600 sm:col-span-2">
              Un e-mail ou un téléphone au minimum, pour que nous puissions vous
              répondre.
            </p>
          </div>
        )}

        {currentStep === 'confirm' && (
          <div className="space-y-4">
            <p className="text-navy-800">
              Vérifiez votre demande avant de l’envoyer.
            </p>
            <dl className="divide-y divide-mist-200 rounded-lg border border-mist-200 bg-white">
              <Summary label="Service" value={service?.label ?? '—'} />
              {service?.requiresRoute && (
                <>
                  <Summary label="Origine"
                           value={[form.originCity, form.originCountry].filter(Boolean).join(', ') || '—'} />
                  <Summary label="Destination"
                           value={[form.destinationCity, form.destinationCountry].filter(Boolean).join(', ') || '—'} />
                </>
              )}
              {service?.requiresCargo && (
                <Summary label="Marchandise" value={form.goods || '—'} />
              )}
              <Summary label="Contact"
                       value={[form.firstName, form.lastName].filter(Boolean).join(' ') || '—'} />
              <Summary label="Société" value={form.companyName || '—'} />
              <Summary label="E-mail" value={form.email || '—'} />
              <Summary label="Téléphone" value={form.phone || '—'} />
            </dl>
          </div>
        )}

        {/* Honeypot: positioned off-screen by CSS, hidden from assistive tech,
            and skipped by keyboard navigation. A real user never fills it. */}
        <div className="dally-honeypot" aria-hidden="true">
          <label htmlFor="website">Site web</label>
          <input
            id="website"
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={form.website}
            onChange={(event) => update('website', event.target.value)}
          />
        </div>
      </div>

      {submitError && (
        <div
          className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800"
          role="alert"
        >
          {submitError}
        </div>
      )}

      <div className="mt-8 flex flex-wrap gap-3">
        {stepIndex > 0 && (
          <button
            type="button"
            onClick={goBack}
            disabled={status === 'submitting'}
            className="rounded-lg border border-navy-300 px-5 py-3 font-medium text-navy-700 disabled:opacity-50"
          >
            Retour
          </button>
        )}
        {!isLastStep ? (
          <button
            type="button"
            onClick={goNext}
            className="rounded-lg bg-navy-700 px-6 py-3 font-semibold text-white hover:bg-navy-600"
          >
            Continuer
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={status === 'submitting'}
            className="rounded-lg bg-green-500 px-6 py-3 font-semibold text-white hover:bg-green-600 disabled:opacity-60"
          >
            {status === 'submitting' ? 'Envoi en cours…' : 'Envoyer ma demande'}
          </button>
        )}
      </div>
    </div>
  );
}

function Field({
  label, value, onChange, type = 'text', required = false, error, placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  error?: string | undefined;
  placeholder?: string;
}) {
  const id = `field-${label.replace(/[^a-zA-Z]/g, '')}`;
  return (
    <div>
      <label className="block font-medium text-navy-800" htmlFor={id}>
        {label}
        {required && <span aria-hidden="true" className="text-red-600"> *</span>}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`mt-2 w-full rounded-lg border p-3 ${
          error ? 'border-red-400' : 'border-mist-300'
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

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 p-3">
      <dt className="text-mist-600">{label}</dt>
      <dd className="text-right font-medium text-navy-800">{value}</dd>
    </div>
  );
}
