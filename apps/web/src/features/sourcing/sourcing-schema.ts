/**
 * Validation of the sourcing form.
 *
 * A separate schema from the quote form, not a variant of it. A quote asks about a
 * route and cargo; a sourcing request asks about a product, a quantity and a budget.
 * Merging them would mean either asking a sourcing prospect for a port of loading or
 * loosening the quote rules until they stop protecting anything.
 *
 * Odoo re-validates everything. This layer exists to give a usable message in French
 * before a round trip, not to be the authority (§32).
 */

import { z } from 'zod';
import type { SourcingRequestInput } from '@/services/odoo/types';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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
 * An empty field means "not decided yet", which is different from zero — a budget of
 * zero is a statement, and a salesperson needs to tell them apart.
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

/** ISO date, checked for shape and for being a real calendar date. */
const isoDate = z
  .string()
  .trim()
  .refine((value) => {
    if (value === '') return true;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime())
      && parsed.toISOString().startsWith(value);
  }, 'Date invalide (format attendu : AAAA-MM-JJ)')
  .transform((value) => (value === '' ? undefined : value))
  .optional();

/** Currencies offered on the form. Odoo validates the code against res.currency. */
export const SOURCING_CURRENCIES = [
  { code: 'XOF', label: 'FCFA (XOF)' },
  { code: 'EUR', label: 'Euro (EUR)' },
  { code: 'USD', label: 'Dollar US (USD)' },
  { code: 'GBP', label: 'Livre sterling (GBP)' },
  { code: 'CNY', label: 'Yuan (CNY)' },
] as const;

export const sourcingFormSchema = z
  .object({
    requestUuid: z
      .string({ error: 'Identifiant de demande manquant' })
      .trim()
      .refine((value) => UUID_RE.test(value), 'Identifiant de demande invalide'),

    // ─── Product ─────────────────────────────────────────────────
    productName: z
      .string({ error: 'Le produit recherché est obligatoire' })
      .trim()
      .min(2, 'Précisez le produit recherché')
      .max(200),
    productDescription: optionalText(10_000),
    specifications: optionalText(10_000),
    productReference: optionalText(100),
    productUrl: optionalText(500),

    // ─── Quantity and budget ─────────────────────────────────────
    quantity: z
      .union([z.string(), z.number()])
      .transform((value, ctx) => {
        const parsed = typeof value === 'number' ? value : Number(value);
        if (!Number.isFinite(parsed)) {
          ctx.addIssue({ code: 'custom', message: 'Quantité invalide' });
          return 0;
        }
        if (parsed <= 0) {
          ctx.addIssue({
            code: 'custom',
            message: 'La quantité doit être supérieure à zéro',
          });
          return 0;
        }
        if (parsed > 1_000_000_000) {
          ctx.addIssue({ code: 'custom', message: 'Quantité trop élevée' });
          return 0;
        }
        return parsed;
      }),
    uom: optionalText(50),
    budget: optionalNumber(1_000_000_000),
    targetUnitPrice: optionalNumber(100_000_000),
    currency: z
      .string()
      .trim()
      .refine(
        (value) =>
          value === '' ||
          SOURCING_CURRENCIES.some((entry) => entry.code === value),
        'Devise invalide',
      )
      .transform((value) => (value === '' ? undefined : value))
      .optional(),

    // ─── Origin and destination ──────────────────────────────────
    preferredOriginCountry: countryCode,
    destinationCountry: countryCode,
    requestedDeadline: isoDate,

    // ─── Contact ─────────────────────────────────────────────────
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

    notes: optionalText(10_000),

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

export type SourcingFormData = z.output<typeof sourcingFormSchema>;

export function isBotSubmission(data: SourcingFormData): boolean {
  return typeof data.website === 'string' && data.website.trim() !== '';
}

/**
 * Map validated data onto the gateway input.
 *
 * Nested to match the API contract. The honeypot and the idempotency key are dropped:
 * the first is anti-spam plumbing, the second describes the call rather than the
 * request.
 */
export function toSourcingInput(data: SourcingFormData): SourcingRequestInput {
  const utm =
    data.utmSource !== undefined ||
    data.utmMedium !== undefined ||
    data.utmCampaign !== undefined
      ? {
          ...(data.utmSource !== undefined && { source: data.utmSource }),
          ...(data.utmMedium !== undefined && { medium: data.utmMedium }),
          ...(data.utmCampaign !== undefined && { campaign: data.utmCampaign }),
        }
      : undefined;

  return {
    serviceCode: 'sourcing',
    customer: {
      lastName: data.lastName,
      ...(data.firstName !== undefined && { firstName: data.firstName }),
      ...(data.companyName !== undefined && { company: data.companyName }),
      ...(data.email !== undefined && { email: data.email }),
      ...(data.phone !== undefined && { phone: data.phone }),
      ...(data.whatsapp !== undefined && { whatsapp: data.whatsapp }),
    },
    product: {
      name: data.productName,
      ...(data.productDescription !== undefined && {
        description: data.productDescription,
      }),
      ...(data.specifications !== undefined && {
        specifications: data.specifications,
      }),
      ...(data.productReference !== undefined && {
        reference: data.productReference,
      }),
      ...(data.productUrl !== undefined && { url: data.productUrl }),
    },
    quantity: data.quantity,
    ...(data.uom !== undefined && { uom: data.uom }),
    ...(data.budget !== undefined && { budget: data.budget }),
    ...(data.targetUnitPrice !== undefined && {
      targetUnitPrice: data.targetUnitPrice,
    }),
    ...(data.currency !== undefined && { currency: data.currency }),
    ...(data.preferredOriginCountry !== undefined && {
      preferredOriginCountry: data.preferredOriginCountry,
    }),
    ...(data.destinationCountry !== undefined && {
      destinationCountry: data.destinationCountry,
    }),
    ...(data.requestedDeadline !== undefined && {
      requestedDeadline: data.requestedDeadline,
    }),
    ...(data.notes !== undefined && { notes: data.notes }),
    ...(data.sourceUrl !== undefined && { sourceUrl: data.sourceUrl }),
    ...(data.referrerUrl !== undefined && { referrerUrl: data.referrerUrl }),
    ...(utm !== undefined && { utm }),
  };
}

// ─── Steps ───────────────────────────────────────────────────────────

export type SourcingStepId =
  | 'product'
  | 'quantity'
  | 'route'
  | 'contact'
  | 'confirm';

export const SOURCING_STEPS: ReadonlyArray<SourcingStepId> = [
  'product',
  'quantity',
  'route',
  'contact',
  'confirm',
];

export const STEP_LABELS: Readonly<Record<SourcingStepId, string>> = {
  product: 'Produit',
  quantity: 'Quantité et budget',
  route: 'Origine et destination',
  contact: 'Coordonnées',
  confirm: 'Confirmation',
};

/**
 * Fields validated on each step.
 *
 * Declared as data so the form validates exactly the step the user is on, and a new
 * field cannot be silently left unchecked.
 */
export const STEP_FIELDS: Readonly<Record<SourcingStepId, ReadonlyArray<string>>> = {
  product: ['productName', 'productDescription', 'specifications',
            'productReference', 'productUrl'],
  quantity: ['quantity', 'uom', 'budget', 'targetUnitPrice', 'currency'],
  route: ['preferredOriginCountry', 'destinationCountry', 'requestedDeadline'],
  contact: ['lastName', 'firstName', 'companyName', 'email', 'phone',
            'whatsapp', 'notes'],
  confirm: [],
};
