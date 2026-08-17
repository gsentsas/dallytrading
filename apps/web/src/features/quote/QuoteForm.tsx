'use client';

/**
 * Multi-step quote form, driven by the service catalogue Odoo publishes.
 *
 * There is no per-service logic in this file. Which steps appear and which fields
 * they contain is derived entirely from the `requires_*` flags on the service —
 * adding a service in Odoo, or changing what it needs, changes this form with no
 * front-end deployment. That is the point of making Odoo the source of truth.
 *
 * The idempotency key is generated once, when the form mounts, and reused on every
 * retry: that is what makes a double-click or a flaky connection safe (§41).
 */

import { useMemo, useState } from 'react';
import type { ServiceType } from '@/services/odoo/types';
import {
  STEP_LABELS,
  quoteRequestSchema,
  stepsForService,
  type QuoteStepId,
} from './quote-schema';

interface FormState {
  serviceCode: string;
  originCountryCode: string;
  originCity: string;
  destinationCountryCode: string;
  destinationCity: string;
  goodsDescription: string;
  quantity: string;
  weightKg: string;
  volumeCbm: string;
  packagesCount: string;
  vehicleMake: string;
  vehicleModel: string;
  vehicleYear: string;
  vehicleVin: string;
  vehicleRegistration: string;
  vehicleColor: string;
  vehicleCategory: string;
  vehicleCondition: string;
  vehicleFuel: string;
  vehicleKeyCount: string;
  vehicleTransportMode: string;
  vehiclePickupRequested: boolean;
  vehiclePickupAddress: string;
  vehicleDeliveryRequested: boolean;
  vehicleDeliveryAddress: string;
  budget: string;
  firstName: string;
  lastName: string;
  companyName: string;
  email: string;
  phone: string;
  whatsapp: string;
  city: string;
  countryCode: string;
  message: string;
  website: string;
}

const EMPTY: FormState = {
  serviceCode: '',
  originCountryCode: '', originCity: '',
  destinationCountryCode: '', destinationCity: '',
  goodsDescription: '', quantity: '', weightKg: '', volumeCbm: '',
  packagesCount: '',
  vehicleMake: '', vehicleModel: '', vehicleYear: '',
  vehicleVin: '', vehicleRegistration: '', vehicleColor: '',
  vehicleCategory: 'car', vehicleCondition: 'running', vehicleFuel: '',
  vehicleKeyCount: '1', vehicleTransportMode: '',
  vehiclePickupRequested: false, vehiclePickupAddress: '',
  vehicleDeliveryRequested: false, vehicleDeliveryAddress: '',
  budget: '',
  firstName: '', lastName: '', companyName: '',
  email: '', phone: '', whatsapp: '',
  city: '', countryCode: '', message: '',
  website: '',
};

type Status = 'editing' | 'submitting' | 'sent' | 'error';

export function QuoteForm({
  services,
  catalogueStale,
  initialServiceCode,
}: {
  services: ReadonlyArray<ServiceType>;
  catalogueStale: boolean;
  /**
   * Service to start on, from `?service=` — set by the CTAs on activity pages.
   *
   * Only honoured when the code exists in the catalogue Odoo published, so a stale
   * link loses the pre-selection instead of putting the form into a state where the
   * chosen service does not exist.
   */
  initialServiceCode?: string;
}) {
  const requestUuid = useMemo(() => crypto.randomUUID(), []);

  const [form, setForm] = useState<FormState>(() =>
    initialServiceCode &&
    services.some((service) => service.code === initialServiceCode)
      ? { ...EMPTY, serviceCode: initialServiceCode }
      : EMPTY,
  );
  const [stepIndex, setStepIndex] = useState(0);
  const [status, setStatus] = useState<Status>('editing');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const service = useMemo(
    () => services.find((entry) => entry.code === form.serviceCode),
    [services, form.serviceCode],
  );
  const steps = useMemo(() => stepsForService(service), [service]);
  const currentStep: QuoteStepId = steps[stepIndex] ?? 'service';

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    setErrors((previous) => {
      if (!previous[key]) return previous;
      const next = { ...previous };
      delete next[key];
      return next;
    });
  }

  function selectService(code: string) {
    // Changing service can remove the step the user is on, so the index is reset
    // rather than left pointing at a step that no longer exists.
    setForm((previous) => ({ ...previous, serviceCode: code }));
    setErrors({});
    setStepIndex(0);
  }

  function validateStep(): boolean {
    const stepErrors: Record<string, string> = {};

    if (currentStep === 'service' && !form.serviceCode) {
      stepErrors.serviceCode = 'Veuillez sélectionner un service.';
    }

    if (currentStep === 'route' && service) {
      if (service.requires_origin && !form.originCity && !form.originCountryCode) {
        stepErrors.originCity = 'L’origine est requise pour ce service.';
      }
      if (
        service.requires_destination &&
        !form.destinationCity &&
        !form.destinationCountryCode
      ) {
        stepErrors.destinationCity = 'La destination est requise pour ce service.';
      }
    }

    if (currentStep === 'contact') {
      if (!form.lastName.trim()) {
        stepErrors.lastName = 'Le nom est obligatoire.';
      }
      if (!form.email.trim() && !form.phone.trim()) {
        stepErrors.email = 'Indiquez au moins un e-mail ou un téléphone.';
      }
      // The shared schema decides what a valid address looks like, so the client
      // and the server can never disagree about it.
      if (form.email.trim()) {
        const probe = quoteRequestSchema.safeParse({
          requestUuid,
          serviceCode: form.serviceCode || 'other',
          lastName: form.lastName || 'x',
          email: form.email,
        });
        if (!probe.success) {
          const issue = probe.error.issues.find((entry) =>
            entry.path.includes('email'),
          );
          if (issue) stepErrors.email = issue.message;
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

    // Structured fields go to structured fields — unlike the earlier lead form,
    // which folded them into a message. The server has somewhere to put them now.
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
      originCountryCode: form.originCountryCode || undefined,
      originCity: form.originCity || undefined,
      destinationCountryCode: form.destinationCountryCode || undefined,
      destinationCity: form.destinationCity || undefined,
      goodsDescription: form.goodsDescription || undefined,
      quantity: form.quantity || undefined,
      weightKg: form.weightKg || undefined,
      volumeCbm: form.volumeCbm || undefined,
      packagesCount: form.packagesCount || undefined,
      vehicleMake: form.vehicleMake || undefined,
      vehicleModel: form.vehicleModel || undefined,
      vehicleYear: form.vehicleYear || undefined,
      vehicleVin: form.vehicleVin || undefined,
      vehicleRegistration: form.vehicleRegistration || undefined,
      vehicleColor: form.vehicleColor || undefined,
      vehicleCategory: form.vehicleCategory || undefined,
      vehicleCondition: form.vehicleCondition || undefined,
      vehicleFuel: form.vehicleFuel || undefined,
      vehicleKeyCount: form.vehicleKeyCount || undefined,
      vehicleTransportMode: form.vehicleTransportMode || undefined,
      // Les adresses ne sont transmises que si la prestation est cochée. Le
      // schéma les écarte aussi, mais les retenir ici évite qu'une valeur
      // masquée traverse la validation pour être supprimée ensuite.
      vehiclePickupRequested: form.vehiclePickupRequested || undefined,
      vehiclePickupAddress: form.vehiclePickupRequested
        ? form.vehiclePickupAddress || undefined
        : undefined,
      vehicleDeliveryRequested: form.vehicleDeliveryRequested || undefined,
      vehicleDeliveryAddress: form.vehicleDeliveryRequested
        ? form.vehicleDeliveryAddress || undefined
        : undefined,
      budget: form.budget || undefined,
      message: form.message || undefined,
      sourceUrl: typeof window !== 'undefined' ? window.location.href : undefined,
      referrerUrl:
        typeof document !== 'undefined' && document.referrer
          ? document.referrer
          : undefined,
      website: form.website || undefined,
    };

    try {
      const response = await fetch('/api/quotes', {
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
      // The same requestUuid is kept, so pressing "réessayer" cannot create a
      // second request if the first call in fact reached the server.
      setSubmitError(
        'Connexion interrompue. Vérifiez votre réseau et réessayez : votre demande ne sera pas envoyée deux fois.',
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
        <h2 className="text-xl font-bold text-green-700">Demande enregistrée</h2>
        <p className="mt-3 text-navy-800">
          Merci. Votre demande a bien été transmise à notre équipe commerciale.
        </p>
        <p className="mt-4 text-navy-800">
          Votre référence :{' '}
          <strong className="font-mono text-lg">{reference}</strong>
        </p>
        <p className="mt-2 text-sm text-mist-600">
          Conservez-la : elle identifie votre demande dans tous nos échanges. Pour
          nous transmettre des documents, répondez à notre e-mail ou écrivez-nous
          sur WhatsApp en indiquant cette référence.
        </p>
      </div>
    );
  }

  const isLastStep = stepIndex === steps.length - 1;

  return (
    <div>
      {catalogueStale && (
        <div
          className="mb-6 rounded-lg border border-mist-300 bg-mist-100 p-3 text-sm text-mist-700"
          role="status"
        >
          Notre catalogue de services est momentanément affiché depuis une copie
          récente. Vous pouvez envoyer votre demande normalement.
        </div>
      )}

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
              {services.map((option) => (
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
                    onChange={() => selectService(option.code)}
                    className="sr-only"
                  />
                  <span className="block font-medium text-navy-700">
                    {option.name}
                  </span>
                  {option.description && (
                    <span className="mt-1 block text-sm text-mist-600">
                      {option.description}
                    </span>
                  )}
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

        {currentStep === 'route' && service && (
          <div className="grid gap-5 sm:grid-cols-2">
            {service.requires_origin && (
              <>
                <Field label="Ville d’origine" value={form.originCity}
                       onChange={(v) => update('originCity', v)}
                       error={errors.originCity}
                       required />
                <Field label="Pays d’origine (code ISO)"
                       value={form.originCountryCode}
                       onChange={(v) => update('originCountryCode', v)}
                       placeholder="FR" />
              </>
            )}
            {service.requires_destination && (
              <>
                <Field label="Ville de destination" value={form.destinationCity}
                       onChange={(v) => update('destinationCity', v)}
                       error={errors.destinationCity}
                       required />
                <Field label="Pays de destination (code ISO)"
                       value={form.destinationCountryCode}
                       onChange={(v) => update('destinationCountryCode', v)}
                       placeholder="SN" />
              </>
            )}
          </div>
        )}

        {currentStep === 'cargo' && service && (
          <div className="space-y-5">
            {service.requires_goods && (
              <>
                <Field label="Nature de la marchandise"
                       value={form.goodsDescription}
                       onChange={(v) => update('goodsDescription', v)}
                       placeholder="Ex. pièces automobiles, textile, riz" />
                <Field label="Quantité" value={form.quantity}
                       onChange={(v) => update('quantity', v)}
                       placeholder="Ex. 3 palettes, 2 tonnes, 500 unités" />
              </>
            )}
            <div className="grid gap-5 sm:grid-cols-3">
              {service.requires_weight && (
                <Field label="Poids (kg)" value={form.weightKg} type="number"
                       onChange={(v) => update('weightKg', v)}
                       error={errors.weightKg} />
              )}
              {service.requires_volume && (
                <>
                  <Field label="Volume (m³)" value={form.volumeCbm} type="number"
                         onChange={(v) => update('volumeCbm', v)}
                         error={errors.volumeCbm} />
                  <Field label="Nombre de colis" value={form.packagesCount}
                         type="number"
                         onChange={(v) => update('packagesCount', v)}
                         error={errors.packagesCount} />
                </>
              )}
            </div>
            <p className="text-sm text-mist-600">
              Ces informations sont facultatives si vous ne les connaissez pas
              encore : nous les préciserons ensemble.
            </p>
          </div>
        )}

        {currentStep === 'vehicle' && (
          <div className="space-y-5">
            <div className="grid gap-5 sm:grid-cols-3">
              <Field label="Marque" value={form.vehicleMake}
                     onChange={(v) => update('vehicleMake', v)}
                     placeholder="Ex. Toyota" />
              <Field label="Modèle" value={form.vehicleModel}
                     onChange={(v) => update('vehicleModel', v)}
                     placeholder="Ex. Hilux" />
              <Field label="Année" value={form.vehicleYear}
                     onChange={(v) => update('vehicleYear', v)}
                     placeholder="Ex. 2019" />
            </div>

            <div className="grid gap-5 sm:grid-cols-3">
              <Field label="Numéro de châssis (VIN)" value={form.vehicleVin}
                     onChange={(v) => update('vehicleVin', v)}
                     placeholder="Ex. JT1234567890ABCDE" />
              <Field label="Immatriculation" value={form.vehicleRegistration}
                     onChange={(v) => update('vehicleRegistration', v)}
                     placeholder="Ex. AB-123-CD" />
              <Field label="Couleur" value={form.vehicleColor}
                     onChange={(v) => update('vehicleColor', v)}
                     placeholder="Ex. Blanc" />
            </div>

            <div className="grid gap-5 sm:grid-cols-3">
              <Choix label="Type de véhicule" value={form.vehicleCategory}
                     onChange={(v) => update('vehicleCategory', v)}
                     options={[
                       ['car', 'Voiture'], ['suv', 'SUV / 4x4'],
                       ['van', 'Utilitaire'], ['motorcycle', 'Moto'],
                       ['truck', 'Camion'], ['other', 'Autre'],
                     ]} />
              <Choix label="État du véhicule" value={form.vehicleCondition}
                     onChange={(v) => update('vehicleCondition', v)}
                     options={[
                       ['running', 'Roulant'],
                       ['non_running', 'Non roulant'],
                     ]} />
              <Choix label="Motorisation" value={form.vehicleFuel}
                     onChange={(v) => update('vehicleFuel', v)}
                     options={[
                       ['', 'Non précisé'], ['petrol', 'Essence'],
                       ['diesel', 'Diesel'], ['hybrid', 'Hybride'],
                       ['electric', 'Électrique'], ['other', 'Autre'],
                     ]} />
            </div>

            <div className="grid gap-5 sm:grid-cols-2">
              {/*
                Le mode est obligatoire, et c'est le champ le plus important de
                cette étape : « transport de véhicule » ne dit pas si la voiture
                part par bateau ou par camion. Sans lui, le serveur refuse — et
                c'est voulu, deviner produirait une expédition fausse.
              */}
              <Choix label="Mode de transport *" value={form.vehicleTransportMode}
                     onChange={(v) => update('vehicleTransportMode', v)}
                     options={[
                       ['', 'À sélectionner'],
                       ['sea', 'Transport maritime'],
                       ['road', 'Transport routier'],
                     ]} />
              <Field label="Nombre de clés" value={form.vehicleKeyCount}
                     onChange={(v) => update('vehicleKeyCount', v)}
                     placeholder="Ex. 2" />
            </div>

            <div className="space-y-4">
              <Bascule label="Je souhaite un enlèvement du véhicule"
                       checked={form.vehiclePickupRequested}
                       onChange={(v) => update('vehiclePickupRequested', v)} />
              {form.vehiclePickupRequested && (
                <Field label="Adresse d'enlèvement" value={form.vehiclePickupAddress}
                       onChange={(v) => update('vehiclePickupAddress', v)}
                       placeholder="Adresse complète" />
              )}

              <Bascule label="Je souhaite une livraison à destination"
                       checked={form.vehicleDeliveryRequested}
                       onChange={(v) => update('vehicleDeliveryRequested', v)} />
              {form.vehicleDeliveryRequested && (
                <Field label="Adresse de livraison" value={form.vehicleDeliveryAddress}
                       onChange={(v) => update('vehicleDeliveryAddress', v)}
                       placeholder="Adresse complète" />
              )}
            </div>
          </div>
        )}

        {currentStep === 'commercial' && (
          <div className="space-y-5">
            <Field label="Budget ou prix cible" value={form.budget}
                   onChange={(v) => update('budget', v)}
                   placeholder="Ex. environ 2 000 000 FCFA, ou 3000 EUR / tonne" />
            <p className="text-sm text-mist-600">
              Indiquez un ordre de grandeur, dans la devise et l’unité qui vous
              conviennent. Cela nous permet d’orienter la recherche.
            </p>
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
              <Summary label="Service" value={service?.name ?? '—'} />
              {service?.requires_origin && (
                <Summary label="Origine"
                         value={[form.originCity, form.originCountryCode]
                           .filter(Boolean).join(', ') || '—'} />
              )}
              {service?.requires_destination && (
                <Summary label="Destination"
                         value={[form.destinationCity, form.destinationCountryCode]
                           .filter(Boolean).join(', ') || '—'} />
              )}
              {service?.requires_goods && (
                <Summary label="Marchandise"
                         value={form.goodsDescription || '—'} />
              )}
              {service?.requires_vehicle && (
                <Summary label="Véhicule"
                         value={[form.vehicleMake, form.vehicleModel,
                                 form.vehicleYear].filter(Boolean).join(' ') || '—'} />
              )}
              {service?.requires_budget && (
                <Summary label="Budget" value={form.budget || '—'} />
              )}
              <Summary label="Contact"
                       value={[form.firstName, form.lastName]
                         .filter(Boolean).join(' ') || '—'} />
              <Summary label="Société" value={form.companyName || '—'} />
              <Summary label="E-mail" value={form.email || '—'} />
              <Summary label="Téléphone" value={form.phone || '—'} />
            </dl>
          </div>
        )}

        {/* Honeypot: off-screen, out of tab order, hidden from assistive tech. */}
        <div className="dally-honeypot" aria-hidden="true">
          <label htmlFor="website">Site web</label>
          <input
            id="website" name="website" type="text" tabIndex={-1}
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

/** Liste déroulante à libellés client — jamais les codes techniques. */
function Choix({
  label, value, onChange, options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<readonly [string, string]>;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-navy-800">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-mist-300 px-3 py-2 text-navy-800"
      >
        {options.map(([code, libelle]) => (
          <option key={code} value={code}>{libelle}</option>
        ))}
      </select>
    </label>
  );
}

/** Case à cocher qui gouverne l'affichage d'un champ dépendant. */
function Bascule({
  label, checked, onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-3 text-navy-800">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-mist-300"
      />
      <span className="text-sm">{label}</span>
    </label>
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
