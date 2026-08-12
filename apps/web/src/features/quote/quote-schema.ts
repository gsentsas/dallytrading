/**
 * Validation of the quote form, driven by the service catalogue.
 *
 * Two layers, deliberately:
 *
 * * **Shape** — a static zod schema covering types, lengths and formats. It never
 *   depends on which service was chosen, so it can run before the catalogue is
 *   known and is cheap to reason about.
 * * **Requirements** — checked against the service's own flags, which come from
 *   Odoo. A conditional zod schema would mean encoding the catalogue's rules in
 *   the front end, i.e. rebuilding the second business list this design removes.
 *
 * Odoo re-checks everything. This layer exists to give a usable error message, not
 * to be the authority (§54).
 */

import { z } from 'zod';
import type { QuoteInput, ServiceType } from '@/services/odoo/types';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Trim, then treat an empty string as absent. */
const optionalText = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .transform((value) => (value === '' ? undefined : value))
    .optional();

/**
 * Optional non-negative number accepted as a string.
 *
 * Forms submit strings. An empty one means "not known yet", which is different
 * from zero — a shipment that weighs nothing does not exist, so zero must not be
 * inferred from silence.
 */
const optionalNumber = (max: number) =>
  z
    .union([z.string(), z.number()])
    .optional()
    .transform((value, ctx) => {
      if (value === undefined || value === '') return undefined;
      const parsed = typeof value === 'number' ? value : Number(value);
      if (!Number.isFinite(parsed)) {
        ctx.addIssue({ code: 'custom', message: 'Valeur numérique invalide' });
        return undefined;
      }
      if (parsed < 0) {
        ctx.addIssue({ code: 'custom', message: 'La valeur ne peut être négative' });
        return undefined;
      }
      if (parsed > max) {
        ctx.addIssue({ code: 'custom', message: 'Valeur trop élevée' });
        return undefined;
      }
      return parsed;
    });

const email = z
  .string()
  .trim()
  .max(254)
  .refine((value) => {
    if (value === '') return true;
    const parts = value.split('@');
    if (parts.length !== 2) return false;
    const [local, domain] = parts;
    if (!local || !domain) return false;
    if (!domain.includes('.') || domain.startsWith('.') || domain.endsWith('.')) {
      return false;
    }
    return !/\s/.test(value);
  }, 'Adresse e-mail invalide')
  .transform((value) => (value === '' ? undefined : value))
  .optional();

/**
 * Phone number.
 *
 * Only length and character set are checked. Rejecting anything that is not a
 * canonical +221 number would turn away legitimate international prospects, which
 * for an import/export business is the wrong trade-off.
 */
const phone = z
  .string()
  .trim()
  .max(40)
  .refine((value) => {
    if (value === '') return true;
    const digits = value.replace(/\D/g, '');
    return digits.length >= 7 && digits.length <= 20;
  }, 'Numéro de téléphone invalide')
  .transform((value) => (value === '' ? undefined : value))
  .optional();

const countryCode = z
  .string()
  .trim()
  .length(2, 'Code pays invalide')
  .regex(/^[A-Za-z]{2}$/, 'Code pays invalide')
  .transform((value) => value.toUpperCase())
  .optional();

export const quoteRequestSchema = z
  .object({
    requestUuid: z
      .string({ error: 'Identifiant de demande manquant' })
      .trim()
      .refine((value) => UUID_RE.test(value), 'Identifiant de demande invalide'),

    serviceCode: z
      .string({ error: 'Veuillez sélectionner un service' })
      .trim()
      .min(1, 'Veuillez sélectionner un service')
      .max(50)
      .regex(/^[a-z0-9_]+$/, 'Code de service invalide'),

    lastName: z
      .string({ error: 'Le nom est obligatoire' })
      .trim()
      .min(1, 'Le nom est obligatoire')
      .max(100),
    firstName: optionalText(100),
    companyName: optionalText(200),

    email,
    phone,
    whatsapp: phone,
    city: optionalText(100),
    countryCode,

    originCountryCode: countryCode,
    originCity: optionalText(100),
    destinationCountryCode: countryCode,
    destinationCity: optionalText(100),

    goodsDescription: optionalText(5000),
    quantity: optionalText(100),
    weightKg: optionalNumber(10_000_000),
    volumeCbm: optionalNumber(100_000),
    packagesCount: optionalNumber(100_000),

    vehicleMake: optionalText(100),
    vehicleModel: optionalText(100),
    vehicleYear: optionalText(10),

    budget: optionalText(100),
    message: optionalText(20_000),

    sourceUrl: optionalText(500),
    referrerUrl: optionalText(500),
    utmSource: optionalText(100),
    utmMedium: optionalText(100),
    utmCampaign: optionalText(100),

    /** Honeypot — hidden from users; a value means an automated submission. */
    website: z.string().max(200).optional(),
  })
  .refine((data) => Boolean(data.email ?? data.phone), {
    message: 'Indiquez au moins un e-mail ou un téléphone',
    path: ['email'],
  });

export type QuoteRequestData = z.output<typeof quoteRequestSchema>;

/** True when the honeypot was filled. */
export function isBotSubmission(data: QuoteRequestData): boolean {
  return typeof data.website === 'string' && data.website.trim() !== '';
}

/**
 * Check a submission against what the chosen service says it needs.
 *
 * Only origin and destination are enforced, matching the server. Weight, volume
 * and budget are genuinely often unknown at enquiry time, and refusing a request
 * because a customer does not yet know their tonnage would turn away real
 * business — the salesperson asks in the follow-up call.
 *
 * Returns field-keyed messages, empty when acceptable.
 */
export function validateServiceRequirements(
  data: QuoteRequestData,
  service: ServiceType | undefined,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!service) {
    errors.serviceCode = 'Service inconnu.';
    return errors;
  }

  if (service.requires_origin && !data.originCity && !data.originCountryCode) {
    errors.originCity = 'L’origine est requise pour ce service.';
  }
  if (
    service.requires_destination &&
    !data.destinationCity &&
    !data.destinationCountryCode
  ) {
    errors.destinationCity = 'La destination est requise pour ce service.';
  }

  return errors;
}

/**
 * Map validated data onto the gateway input.
 *
 * The honeypot and the idempotency key are dropped: the first is anti-spam
 * plumbing, the second travels as a separate argument because it describes the
 * call, not the request.
 */
export function toQuoteInput(data: QuoteRequestData): QuoteInput {
  return {
    serviceCode: data.serviceCode,
    lastName: data.lastName,
    ...(data.firstName !== undefined && { firstName: data.firstName }),
    ...(data.companyName !== undefined && { companyName: data.companyName }),
    ...(data.email !== undefined && { email: data.email }),
    ...(data.phone !== undefined && { phone: data.phone }),
    ...(data.whatsapp !== undefined && { whatsapp: data.whatsapp }),
    ...(data.city !== undefined && { city: data.city }),
    ...(data.countryCode !== undefined && { countryCode: data.countryCode }),
    ...(data.originCountryCode !== undefined && {
      originCountryCode: data.originCountryCode,
    }),
    ...(data.originCity !== undefined && { originCity: data.originCity }),
    ...(data.destinationCountryCode !== undefined && {
      destinationCountryCode: data.destinationCountryCode,
    }),
    ...(data.destinationCity !== undefined && {
      destinationCity: data.destinationCity,
    }),
    ...(data.goodsDescription !== undefined && {
      goodsDescription: data.goodsDescription,
    }),
    ...(data.quantity !== undefined && { quantity: data.quantity }),
    ...(data.weightKg !== undefined && { weightKg: data.weightKg }),
    ...(data.volumeCbm !== undefined && { volumeCbm: data.volumeCbm }),
    ...(data.packagesCount !== undefined && {
      packagesCount: data.packagesCount,
    }),
    ...(data.vehicleMake !== undefined && { vehicleMake: data.vehicleMake }),
    ...(data.vehicleModel !== undefined && { vehicleModel: data.vehicleModel }),
    ...(data.vehicleYear !== undefined && { vehicleYear: data.vehicleYear }),
    ...(data.budget !== undefined && { budget: data.budget }),
    ...(data.message !== undefined && { message: data.message }),
    ...(data.sourceUrl !== undefined && { sourceUrl: data.sourceUrl }),
    ...(data.referrerUrl !== undefined && { referrerUrl: data.referrerUrl }),
    ...(data.utmSource !== undefined && { utmSource: data.utmSource }),
    ...(data.utmMedium !== undefined && { utmMedium: data.utmMedium }),
    ...(data.utmCampaign !== undefined && { utmCampaign: data.utmCampaign }),
  };
}

// ─── Steps, derived from the service's own flags ────────────────────

export type QuoteStepId =
  | 'service'
  | 'route'
  | 'cargo'
  | 'vehicle'
  | 'commercial'
  | 'contact'
  | 'confirm';

export const STEP_LABELS: Readonly<Record<QuoteStepId, string>> = {
  service: 'Service',
  route: 'Trajet',
  cargo: 'Marchandise',
  vehicle: 'Véhicule',
  commercial: 'Budget',
  contact: 'Coordonnées',
  confirm: 'Confirmation',
};

/**
 * Steps to show for a service.
 *
 * Derived entirely from the flags Odoo publishes — there is no per-service
 * special case in this file. Adding a service in Odoo, or changing what it
 * requires, changes the form with no front-end deployment.
 */
export function stepsForService(
  service: ServiceType | undefined,
): ReadonlyArray<QuoteStepId> {
  const steps: QuoteStepId[] = ['service'];
  if (!service) {
    return [...steps, 'contact', 'confirm'];
  }

  if (service.requires_origin || service.requires_destination) {
    steps.push('route');
  }
  if (service.requires_vehicle) {
    steps.push('vehicle');
  } else if (
    service.requires_goods ||
    service.requires_weight ||
    service.requires_volume
  ) {
    steps.push('cargo');
  }
  if (service.requires_budget) {
    steps.push('commercial');
  }

  steps.push('contact', 'confirm');
  return steps;
}
