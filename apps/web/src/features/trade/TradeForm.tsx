'use client';

/**
 * Multi-step trading enquiry form.
 *
 * Six steps, fixed. The first is the operation type, and it comes first on purpose:
 * it is the question that changes what the rest of the conversation is about, and a
 * prospect who answers it has already told the sales team most of what they need.
 *
 * The idempotency key is generated once on mount and reused on every retry, so a
 * double-click or a dropped connection cannot create two deals.
 *
 * Reuses the existing design system throughout — no trading-specific styling, and the
 * same field primitives as the quote and sourcing forms so all three behave
 * identically for a keyboard and a screen reader.
 *
 * There is no field here for a price, a cost, a margin or a commission. Those are not
 * "hidden": the schema this form validates against has no such key, so there is
 * nothing to hide.
 */

import { useMemo, useState } from 'react';
import {
  STEP_FIELDS,
  STEP_LABELS,
  TRADE_OPERATION_TYPES,
  TRADE_STEPS,
  tradeFormSchema,
  type TradeStepId,
} from './trade-schema';

interface FormState {
  operationType: string;
  subject: string;
  description: string;
  requirements: string;
  contactName: string;
  company: string;
  email: string;
  phone: string;
  whatsapp: string;
  contactCountry: string;
  originCountry: string;
  destinationCountry: string;
  website: string;
}

const EMPTY: FormState = {
  operationType: '',
  subject: '', description: '', requirements: '',
  contactName: '', company: '', email: '', phone: '', whatsapp: '',
  contactCountry: '', originCountry: '', destinationCountry: '',
  website: '',
};

type Status = 'editing' | 'submitting' | 'sent' | 'error';

export function TradeForm() {
  const requestUuid = useMemo(() => crypto.randomUUID(), []);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [stepIndex, setStepIndex] = useState(0);
  const [status, setStatus] = useState<Status>('editing');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const currentStep: TradeStepId = TRADE_STEPS[stepIndex] ?? 'operation';
  const isLastStep = stepIndex === TRADE_STEPS.length - 1;

  const selectedType = TRADE_OPERATION_TYPES.find(
    (type) => type.value === form.operationType,
  );

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    if (errors[key as string]) {
      setErrors((previous) => {
        const next = { ...previous };
        delete next[key as string];
        return next;
      });
    }
  }

  function buildPayload() {
    return {
      requestUuid,
      operationType: form.operationType,
      subject: form.subject,
      description: form.description || undefined,
      requirements: form.requirements || undefined,
      contactName: form.contactName,
      company: form.company || undefined,
      email: form.email || undefined,
      phone: form.phone || undefined,
      whatsapp: form.whatsapp || undefined,
      contactCountry: form.contactCountry || undefined,
      originCountry: form.originCountry || undefined,
      destinationCountry: form.destinationCountry || undefined,
      sourceUrl: typeof window !== 'undefined' ? window.location.href : undefined,
      referrerUrl:
        typeof document !== 'undefined' && document.referrer
          ? document.referrer
          : undefined,
      website: form.website || undefined,
    };
  }

  /**
   * Validate only the fields belonging to the current step.
   *
   * Runs the shared schema and keeps the issues whose path is on this step, so client
   * and server can never disagree about what is acceptable — while a missing field
   * three steps ahead does not block the user here.
   */
  function validateStep(): boolean {
    const result = tradeFormSchema.safeParse(buildPayload());
    if (result.success) {
      setErrors({});
      return true;
    }

    const relevant = new Set(STEP_FIELDS[currentStep]);
    const stepErrors: Record<string, string> = {};
    for (const issue of result.error.issues) {
      const field = issue.path.join('.');
      if (relevant.has(field)) {
        stepErrors[field] ??= issue.message;
      }
      // The email-or-phone rule reports on `email`, which lives on the contact step.
      if (field === 'email' && currentStep === 'contact') {
        stepErrors.email ??= issue.message;
      }
    }

    setErrors(stepErrors);
    return Object.keys(stepErrors).length === 0;
  }

  function goNext() {
    if (!validateStep()) return;
    setStepIndex((index) => Math.min(index + 1, TRADE_STEPS.length - 1));
  }

  function goBack() {
    setErrors({});
    setStepIndex((index) => Math.max(index - 1, 0));
  }

  async function submit() {
    // The whole payload, not just this step: the review step has no fields of its
    // own, so this is the first full check.
    const payload = buildPayload();
    const result = tradeFormSchema.safeParse(payload);
    if (!result.success) {
      const fields: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const field = issue.path.join('.') || 'form';
        fields[field] ??= issue.message;
      }
      setErrors(fields);
      setSubmitError(
        'Certains champs sont incomplets. Revenez aux étapes précédentes pour les corriger.',
      );
      setStatus('error');
      return;
    }

    setStatus('submitting');
    setSubmitError(null);

    try {
      const response = await fetch('/api/trade', {
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
      // The same requestUuid is kept, so pressing retry cannot create a second deal
      // if the first call in fact reached the server.
      setSubmitError(
        'Connexion interrompue. Vérifiez votre réseau et réessayez : votre demande ne sera pas envoyée deux fois.',
      );
      setStatus('error');
    }
  }

  // ─── Confirmation ───────────────────────────────────────────────
  if (status === 'sent' && reference) {
    return (
      <div
        className="rounded-xl border border-green-200 bg-green-50 p-6"
        role="status"
        aria-live="polite"
      >
        <h2 className="text-xl font-bold text-green-800">
          Votre demande a bien été enregistrée
        </h2>
        <p className="mt-3 text-navy-800">
          Notre équipe étudie votre opération et revient vers vous pour en préciser la
          structure et les conditions.
        </p>
        <p className="mt-4 text-navy-800">
          Référence : <strong className="font-mono text-lg">{reference}</strong>
        </p>
        <p className="mt-2 text-sm text-mist-600">
          Conservez-la : elle identifie votre demande dans tous nos échanges. Pour nous
          transmettre des documents, répondez à notre e-mail ou écrivez-nous sur
          WhatsApp en indiquant cette référence.
        </p>
      </div>
    );
  }

  return (
    <div>
      <ol className="mb-8 flex flex-wrap gap-2" aria-hidden="true">
        {TRADE_STEPS.map((step, index) => (
          <li
            key={step}
            className={`rounded-full px-3 py-1 text-sm ${
              index === stepIndex
                ? 'bg-navy-700 text-white'
                : index < stepIndex
                  ? 'bg-green-100 text-green-800'
                  : 'bg-mist-100 text-mist-600'
            }`}
          >
            {index + 1}. {STEP_LABELS[step]}
          </li>
        ))}
      </ol>

      <h2 className="text-xl font-bold text-navy-800">
        Étape {stepIndex + 1} sur {TRADE_STEPS.length} — {STEP_LABELS[currentStep]}
      </h2>

      <div className="mt-6 space-y-5">
        {/* ─── 1. Operation type ─────────────────────────────────── */}
        {currentStep === 'operation' && (
          <fieldset>
            <legend className="font-medium text-navy-800">
              Quel type d’opération envisagez-vous ?
              <span aria-hidden="true" className="text-red-700"> *</span>
            </legend>
            <p className="mt-1 text-sm text-mist-600">
              Si vous hésitez, choisissez ce qui s’en rapproche le plus : nous en
              reparlerons ensemble.
            </p>
            <div className="mt-4 space-y-3">
              {TRADE_OPERATION_TYPES.map((type) => (
                <label
                  key={type.value}
                  className={`flex cursor-pointer gap-3 rounded-lg border p-4 ${
                    form.operationType === type.value
                      ? 'border-navy-700 bg-navy-50'
                      : 'border-mist-300'
                  }`}
                >
                  <input
                    type="radio"
                    name="operationType"
                    value={type.value}
                    checked={form.operationType === type.value}
                    onChange={() => update('operationType', type.value)}
                    className="mt-1"
                  />
                  <span>
                    <span className="block font-medium text-navy-800">
                      {type.label}
                    </span>
                    <span className="block text-sm text-mist-600">{type.hint}</span>
                  </span>
                </label>
              ))}
            </div>
            {errors.operationType && (
              <p className="mt-2 text-sm text-red-700" role="alert">
                {errors.operationType}
              </p>
            )}
          </fieldset>
        )}

        {/* ─── 2. Subject ────────────────────────────────────────── */}
        {currentStep === 'subject' && (
          <>
            <Field
              label="Objet de votre demande"
              value={form.subject}
              onChange={(value) => update('subject', value)}
              required
              placeholder="Ex. : approvisionnement en riz parfumé depuis l’Asie"
              error={errors.subject}
            />
            <TextArea
              label="Description"
              value={form.description}
              onChange={(value) => update('description', value)}
              placeholder="Le contexte, les volumes envisagés, l’échéance…"
              error={errors.description}
            />
          </>
        )}

        {/* ─── 3. Requirement ────────────────────────────────────── */}
        {currentStep === 'requirement' && (
          <>
            <TextArea
              label="Votre besoin en détail"
              value={form.requirements}
              onChange={(value) => update('requirements', value)}
              placeholder="Spécifications, certifications attendues, conditions de paiement souhaitées, contraintes de délai…"
              error={errors.requirements}
            />
            <p className="text-sm text-mist-600">
              Plus votre besoin est précis, plus notre première réponse le sera.
              Aucune information commerciale sensible n’est nécessaire à ce stade.
            </p>
          </>
        )}

        {/* ─── 4. Flow ───────────────────────────────────────────── */}
        {currentStep === 'flow' && (
          <>
            <p className="text-sm text-mist-600">
              Ces deux champs sont facultatifs. Ils nous permettent d’orienter la
              demande vers la bonne équipe dès la première lecture.
            </p>
            <Field
              label="Pays d’origine"
              value={form.originCountry}
              onChange={(value) => update('originCountry', value)}
              placeholder="Code à deux lettres, ex. CN"
              error={errors.originCountry}
            />
            <Field
              label="Pays de destination"
              value={form.destinationCountry}
              onChange={(value) => update('destinationCountry', value)}
              placeholder="Code à deux lettres, ex. SN"
              error={errors.destinationCountry}
            />
          </>
        )}

        {/* ─── 5. Contact ────────────────────────────────────────── */}
        {currentStep === 'contact' && (
          <>
            <Field
              label="Nom et prénom"
              value={form.contactName}
              onChange={(value) => update('contactName', value)}
              required
              autoComplete="name"
              error={errors.contactName}
            />
            <Field
              label="Société"
              value={form.company}
              onChange={(value) => update('company', value)}
              autoComplete="organization"
              error={errors.company}
            />
            <Field
              label="E-mail"
              type="email"
              value={form.email}
              onChange={(value) => update('email', value)}
              autoComplete="email"
              error={errors.email}
            />
            <Field
              label="Téléphone"
              type="tel"
              value={form.phone}
              onChange={(value) => update('phone', value)}
              autoComplete="tel"
              error={errors.phone}
            />
            <Field
              label="WhatsApp"
              value={form.whatsapp}
              onChange={(value) => update('whatsapp', value)}
              placeholder="Si différent du téléphone"
              error={errors.whatsapp}
            />
            <Field
              label="Votre pays"
              value={form.contactCountry}
              onChange={(value) => update('contactCountry', value)}
              placeholder="Code à deux lettres, ex. SN"
              error={errors.contactCountry}
            />
            <p className="text-sm text-mist-600">
              Indiquez au moins un e-mail ou un téléphone : sans cela, nous ne pourrons
              pas vous répondre.
            </p>
          </>
        )}

        {/* ─── 6. Review ─────────────────────────────────────────── */}
        {currentStep === 'review' && (
          <div className="space-y-4">
            <dl className="divide-y divide-mist-200 rounded-lg border border-mist-200">
              <Summary
                label="Type d’opération"
                value={selectedType?.label ?? '—'}
              />
              <Summary label="Objet" value={form.subject || '—'} />
              <Summary label="Contact" value={form.contactName || '—'} />
              <Summary label="Société" value={form.company || '—'} />
              <Summary label="E-mail" value={form.email || '—'} />
              <Summary label="Téléphone" value={form.phone || '—'} />
              <Summary label="Origine" value={form.originCountry || '—'} />
              <Summary label="Destination" value={form.destinationCountry || '—'} />
            </dl>
            <p className="text-sm text-mist-600">
              Vous recevrez une référence dès l’envoi. Le téléversement de documents
              n’est pas encore disponible : vous pourrez nous les transmettre par
              e-mail ou WhatsApp en citant cette référence.
            </p>
          </div>
        )}

        {/* Honeypot: off-screen, out of tab order, hidden from assistive tech. */}
        <div className="dally-honeypot" aria-hidden="true">
          <label htmlFor="trade-website">Site web</label>
          <input
            id="trade-website" name="website" type="text" tabIndex={-1}
            autoComplete="off" value={form.website}
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
            type="button" onClick={goBack} disabled={status === 'submitting'}
            className="rounded-lg border border-navy-300 px-5 py-3 font-medium text-navy-700 disabled:opacity-50"
          >
            Retour
          </button>
        )}
        {!isLastStep ? (
          <button
            type="button" onClick={goNext}
            className="rounded-lg bg-navy-700 px-6 py-3 font-semibold text-white hover:bg-navy-600"
          >
            Continuer
          </button>
        ) : (
          <button
            type="button" onClick={submit} disabled={status === 'submitting'}
            className="rounded-lg bg-green-700 px-6 py-3 font-semibold text-white hover:bg-green-800 disabled:opacity-60"
          >
            {status === 'submitting' ? 'Envoi en cours…' : 'Envoyer ma demande'}
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Field primitives ────────────────────────────────────────────────
// Local to this form and matching the quote and sourcing forms' markup, so the three
// behave identically for a keyboard and a screen reader.

function fieldId(label: string): string {
  return `trade-${label.replace(/[^a-zA-Z]/g, '').toLowerCase()}`;
}

function Field({
  label, value, onChange, type = 'text', required = false, error, placeholder,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  error?: string | undefined;
  placeholder?: string;
  autoComplete?: string;
}) {
  const id = fieldId(label);
  return (
    <div>
      <label className="block font-medium text-navy-800" htmlFor={id}>
        {label}
        {required && <span aria-hidden="true" className="text-red-700"> *</span>}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
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

function TextArea({
  label, value, onChange, error, placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | undefined;
  placeholder?: string;
}) {
  const id = fieldId(label);
  return (
    <div>
      <label className="block font-medium text-navy-800" htmlFor={id}>
        {label}
      </label>
      <textarea
        id={id}
        rows={5}
        value={value}
        placeholder={placeholder}
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

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 p-3">
      <dt className="text-mist-600">{label}</dt>
      <dd className="text-right font-medium text-navy-800">{value}</dd>
    </div>
  );
}
