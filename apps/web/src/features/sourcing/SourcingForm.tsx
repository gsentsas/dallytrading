'use client';

/**
 * Multi-step sourcing form (§36).
 *
 * Five steps, fixed: unlike the quote form, the questions do not depend on a service —
 * a sourcing request always needs a product, a quantity and a way to reply.
 *
 * The idempotency key is generated once on mount and reused on every retry, so a
 * double-click or a dropped connection cannot create two requests.
 *
 * Reuses the existing design system throughout: no sourcing-specific styling (§54).
 */

import { useMemo, useState } from 'react';
import {
  SOURCING_CURRENCIES,
  SOURCING_STEPS,
  STEP_FIELDS,
  STEP_LABELS,
  sourcingFormSchema,
  type SourcingStepId,
} from './sourcing-schema';

interface FormState {
  productName: string;
  productDescription: string;
  specifications: string;
  productReference: string;
  productUrl: string;
  quantity: string;
  uom: string;
  budget: string;
  targetUnitPrice: string;
  currency: string;
  preferredOriginCountry: string;
  destinationCountry: string;
  requestedDeadline: string;
  lastName: string;
  firstName: string;
  companyName: string;
  email: string;
  phone: string;
  whatsapp: string;
  notes: string;
  website: string;
}

const EMPTY: FormState = {
  productName: '', productDescription: '', specifications: '',
  productReference: '', productUrl: '',
  quantity: '', uom: '', budget: '', targetUnitPrice: '', currency: 'XOF',
  preferredOriginCountry: '', destinationCountry: 'SN', requestedDeadline: '',
  lastName: '', firstName: '', companyName: '',
  email: '', phone: '', whatsapp: '', notes: '',
  website: '',
};

type Status = 'editing' | 'submitting' | 'sent' | 'error';

export function SourcingForm() {
  const requestUuid = useMemo(() => crypto.randomUUID(), []);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [stepIndex, setStepIndex] = useState(0);
  const [status, setStatus] = useState<Status>('editing');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const currentStep: SourcingStepId = SOURCING_STEPS[stepIndex] ?? 'product';
  const isLastStep = stepIndex === SOURCING_STEPS.length - 1;

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    setErrors((previous) => {
      if (!previous[key]) return previous;
      const next = { ...previous };
      delete next[key];
      return next;
    });
  }

  /** Build the payload the API expects, from the current form state. */
  function buildPayload() {
    return {
      requestUuid,
      productName: form.productName,
      productDescription: form.productDescription || undefined,
      specifications: form.specifications || undefined,
      productReference: form.productReference || undefined,
      productUrl: form.productUrl || undefined,
      quantity: form.quantity,
      uom: form.uom || undefined,
      budget: form.budget || undefined,
      targetUnitPrice: form.targetUnitPrice || undefined,
      currency: form.currency || undefined,
      preferredOriginCountry: form.preferredOriginCountry || undefined,
      destinationCountry: form.destinationCountry || undefined,
      requestedDeadline: form.requestedDeadline || undefined,
      lastName: form.lastName,
      firstName: form.firstName || undefined,
      companyName: form.companyName || undefined,
      email: form.email || undefined,
      phone: form.phone || undefined,
      whatsapp: form.whatsapp || undefined,
      notes: form.notes || undefined,
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
   * Runs the shared schema and keeps the issues whose path is on this step, so the
   * client and the server can never disagree about what is acceptable — while a
   * missing field three steps ahead does not block the user here.
   */
  function validateStep(): boolean {
    const result = sourcingFormSchema.safeParse(buildPayload());
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
      // The email/phone rule is reported on `email`, which lives on the contact step.
      if (field === '' && currentStep === 'contact') {
        stepErrors.email ??= issue.message;
      }
    }

    setErrors(stepErrors);
    return Object.keys(stepErrors).length === 0;
  }

  function goNext() {
    if (!validateStep()) return;
    setStepIndex((index) => Math.min(index + 1, SOURCING_STEPS.length - 1));
  }

  function goBack() {
    setErrors({});
    setStepIndex((index) => Math.max(index - 1, 0));
  }

  async function submit() {
    // The whole payload, not just this step: the confirmation step has no fields of
    // its own, so this is the first full check.
    const payload = buildPayload();
    const result = sourcingFormSchema.safeParse(payload);
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
      const response = await fetch('/api/sourcing', {
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
      // The same requestUuid is kept, so pressing retry cannot create a second
      // request if the first call in fact reached the server.
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
          Votre demande de sourcing a bien été enregistrée
        </h2>
        <p className="mt-3 text-navy-800">
          Notre équipe étudie votre besoin et revient vers vous avec les fournisseurs
          identifiés et une proposition chiffrée.
        </p>
        <p className="mt-4 text-navy-800">
          Référence : <strong className="font-mono text-lg">{reference}</strong>
        </p>
        <p className="mt-2 text-sm text-mist-600">
          Conservez-la : elle identifie votre demande dans tous nos échanges. Pour nous
          transmettre des documents ou des photos, répondez à notre e-mail ou
          écrivez-nous sur WhatsApp en indiquant cette référence.
        </p>
      </div>
    );
  }

  return (
    <div>
      <ol className="mb-8 flex flex-wrap gap-2" aria-hidden="true">
        {SOURCING_STEPS.map((step, index) => (
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
        Étape {stepIndex + 1} sur {SOURCING_STEPS.length} — {STEP_LABELS[currentStep]}
      </h2>

      <div className="mt-6 space-y-5">
        {currentStep === 'product' && (
          <>
            <Field
              label="Produit recherché" required value={form.productName}
              onChange={(v) => update('productName', v)} error={errors.productName}
              placeholder="Ex. groupes électrogènes 10 kVA, riz brisé, panneaux solaires"
            />
            <TextArea
              label="Description" value={form.productDescription}
              onChange={(v) => update('productDescription', v)}
              error={errors.productDescription}
              placeholder="À quoi le produit doit-il servir ? Quelles caractéristiques comptent le plus ?"
            />
            <TextArea
              label="Spécifications techniques" value={form.specifications}
              onChange={(v) => update('specifications', v)}
              error={errors.specifications}
              placeholder="Normes, dimensions, matériaux, conditionnement, certifications attendues…"
            />
            <div className="grid gap-5 sm:grid-cols-2">
              <Field
                label="Référence ou modèle" value={form.productReference}
                onChange={(v) => update('productReference', v)}
                error={errors.productReference}
                placeholder="Si vous la connaissez"
              />
              <Field
                label="Lien vers un produit similaire" type="url"
                value={form.productUrl}
                onChange={(v) => update('productUrl', v)} error={errors.productUrl}
                placeholder="https://…"
              />
            </div>
            <p className="text-sm text-mist-600">
              Plus votre description est précise, plus notre recherche sera pertinente.
              Vous n’avez pas besoin de connaître un fournisseur : c’est notre travail.
            </p>
          </>
        )}

        {currentStep === 'quantity' && (
          <>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field
                label="Quantité" required type="number" value={form.quantity}
                onChange={(v) => update('quantity', v)} error={errors.quantity}
                placeholder="Ex. 500"
              />
              <Field
                label="Unité" value={form.uom}
                onChange={(v) => update('uom', v)} error={errors.uom}
                placeholder="Ex. unités, tonnes, cartons"
              />
            </div>
            <div className="grid gap-5 sm:grid-cols-3">
              <Field
                label="Budget total" type="number" value={form.budget}
                onChange={(v) => update('budget', v)} error={errors.budget}
              />
              <Field
                label="Prix cible unitaire" type="number"
                value={form.targetUnitPrice}
                onChange={(v) => update('targetUnitPrice', v)}
                error={errors.targetUnitPrice}
              />
              <Select
                label="Devise" value={form.currency}
                onChange={(v) => update('currency', v)} error={errors.currency}
                options={SOURCING_CURRENCIES.map((entry) => ({
                  value: entry.code, label: entry.label,
                }))}
              />
            </div>
            <p className="text-sm text-mist-600">
              Un ordre de grandeur suffit. Le budget compte autant que le produit : il
              détermine la gamme de fournisseurs à cibler.
            </p>
          </>
        )}

        {currentStep === 'route' && (
          <>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field
                label="Pays fournisseur souhaité (code ISO)"
                value={form.preferredOriginCountry}
                onChange={(v) => update('preferredOriginCountry', v)}
                error={errors.preferredOriginCountry}
                placeholder="Ex. CN, TR, IN, FR"
              />
              <Field
                label="Pays de destination (code ISO)"
                value={form.destinationCountry}
                onChange={(v) => update('destinationCountry', v)}
                error={errors.destinationCountry}
                placeholder="Ex. SN"
              />
            </div>
            <Field
              label="Réponse souhaitée avant le" type="date"
              value={form.requestedDeadline}
              onChange={(v) => update('requestedDeadline', v)}
              error={errors.requestedDeadline}
            />
            <p className="text-sm text-mist-600">
              Ces informations sont facultatives. Si vous n’avez pas de préférence de
              pays, laissez le champ vide : nous chercherons là où le produit se trouve.
            </p>
          </>
        )}

        {currentStep === 'contact' && (
          <>
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
                label="Entreprise" value={form.companyName}
                onChange={(v) => update('companyName', v)} error={errors.companyName}
                autoComplete="organization"
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
            </div>
            <TextArea
              label="Précisions" value={form.notes}
              onChange={(v) => update('notes', v)} error={errors.notes}
            />
            <p className="text-sm text-mist-600">
              Un e-mail ou un téléphone au minimum, pour que nous puissions vous
              répondre.
            </p>
          </>
        )}

        {currentStep === 'confirm' && (
          <div className="space-y-4">
            <p className="text-navy-800">
              Vérifiez votre demande avant de l’envoyer.
            </p>
            <dl className="divide-y divide-mist-200 rounded-lg border border-mist-200 bg-white">
              <Summary label="Produit" value={form.productName || '—'} />
              <Summary
                label="Quantité"
                value={[form.quantity, form.uom].filter(Boolean).join(' ') || '—'}
              />
              <Summary
                label="Budget"
                value={
                  form.budget
                    ? `${form.budget} ${form.currency}`
                    : '—'
                }
              />
              <Summary
                label="Pays fournisseur"
                value={form.preferredOriginCountry || 'Sans préférence'}
              />
              <Summary
                label="Destination" value={form.destinationCountry || '—'}
              />
              <Summary
                label="Réponse souhaitée" value={form.requestedDeadline || '—'}
              />
              <Summary
                label="Contact"
                value={[form.firstName, form.lastName].filter(Boolean).join(' ') || '—'}
              />
              <Summary label="Entreprise" value={form.companyName || '—'} />
              <Summary label="E-mail" value={form.email || '—'} />
              <Summary label="Téléphone" value={form.phone || '—'} />
            </dl>
            <p className="text-sm text-mist-600">
              Vous recevrez une référence dès l’envoi. Le téléversement de documents
              n’est pas encore disponible : vous pourrez nous les transmettre par e-mail
              ou WhatsApp en citant cette référence.
            </p>
          </div>
        )}

        {/* Honeypot: off-screen, out of tab order, hidden from assistive tech. */}
        <div className="dally-honeypot" aria-hidden="true">
          <label htmlFor="sourcing-website">Site web</label>
          <input
            id="sourcing-website" name="website" type="text" tabIndex={-1}
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
            {status === 'submitting'
              ? 'Envoi en cours…'
              : 'Déposer ma demande de sourcing'}
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Field primitives ────────────────────────────────────────────────
// Local to this form and matching the quote form's markup, so the two behave
// identically for a keyboard and a screen reader.

function fieldId(label: string): string {
  return `sourcing-${label.replace(/[^a-zA-Z]/g, '').toLowerCase()}`;
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
        rows={4}
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

function Select({
  label, value, onChange, options, error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  error?: string | undefined;
}) {
  const id = fieldId(label);
  return (
    <div>
      <label className="block font-medium text-navy-800" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        className={`mt-2 w-full rounded-lg border bg-white p-3 ${
          error ? 'border-red-500' : 'border-mist-300'
        }`}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {error && (
        <p className="mt-1 text-sm text-red-700" role="alert">{error}</p>
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
