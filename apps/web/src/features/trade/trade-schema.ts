/**
 * Validation of the trading enquiry form.
 *
 * A separate schema from sourcing, not a variant of it. Sourcing asks "find me this
 * product": a product, a quantity, a budget. Trading asks "let us do business
 * together": what kind of operation, on what flow, with what requirement. Merging them
 * would mean asking a broker for a quantity, or loosening the sourcing rules until
 * they stop protecting anything.
 *
 * Odoo re-validates everything. This layer exists to give a usable message in French
 * before a round trip, not to be the authority.
 *
 * What this schema deliberately cannot express: a price, a cost, a margin, a
 * commission, a supplier. Those are not optional fields left out of the form — they
 * are absent from the type, so no amount of client tampering puts them on the wire.
 */

import { z } from 'zod';
import type { TradeOpportunityInput } from '@/services/odoo/types';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const optionalText = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .transform((value) => (value === '' ? undefined : value))
    .optional();

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

/**
 * The six operation types, with the wording a prospect recognises.
 *
 * `label` is the option text; `hint` is what the form shows underneath, because
 * "courtage" and "commission" are genuinely confused by people who are not in the
 * trade — and a prospect who picks the wrong one costs a qualification call.
 */
export const TRADE_OPERATION_TYPES = [
  {
    value: 'purchase_resale',
    label: 'Achat-revente',
    hint: 'DallyTrading achète la marchandise et vous la revend.',
  },
  {
    value: 'import_export',
    label: 'Import-Export',
    hint: 'Achat et revente à l’international, avec la logistique associée.',
  },
  {
    value: 'distribution',
    label: 'Distribution',
    hint: 'Accord durable de distribution sur un marché ou un territoire.',
  },
  {
    value: 'brokerage',
    label: 'Courtage',
    hint: 'Nous mettons en relation acheteur et vendeur, sans acheter nous-mêmes.',
  },
  {
    value: 'commission',
    label: 'Commission',
    hint: 'Nous intervenons sur votre transaction et sommes rémunérés à la commission.',
  },
  {
    value: 'commercial_representation',
    label: 'Représentation commerciale',
    hint: 'Nous vous représentons commercialement sur un territoire.',
  },
] as const;

export type TradeOperationTypeValue =
  (typeof TRADE_OPERATION_TYPES)[number]['value'];

const OPERATION_VALUES = TRADE_OPERATION_TYPES.map((type) => type.value) as [
  TradeOperationTypeValue,
  ...TradeOperationTypeValue[],
];

export const tradeFormSchema = z
  .object({
    /** Client-generated, so a double click or a retry does not create two deals. */
    requestUuid: z
      .string({ error: 'Identifiant de demande manquant' })
      .regex(UUID_RE, 'Identifiant de demande invalide'),

    operationType: z.enum(OPERATION_VALUES, {
      error: 'Choisissez un type d’opération',
    }),

    subject: z
      .string({ error: 'Précisez l’objet de votre demande' })
      .trim()
      .min(3, 'Précisez l’objet de votre demande')
      .max(200, 'Objet trop long (200 caractères maximum)'),

    description: optionalText(10_000),
    requirements: optionalText(10_000),

    contactName: z
      .string({ error: 'Votre nom est requis' })
      .trim()
      .min(2, 'Votre nom est requis')
      .max(200, 'Nom trop long'),
    company: optionalText(200),
    email,
    phone,
    whatsapp: optionalText(40),
    contactCountry: countryCode,

    originCountry: countryCode,
    destinationCountry: countryCode,

    /**
     * Honeypot. A real person never sees this field, so anything in it is a bot.
     * Named plausibly on purpose: `honeypot` would be skipped by anything competent.
     */
    website: z.string().max(200).optional(),

    sourceUrl: optionalText(500),
    referrerUrl: optionalText(500),
  })
  .refine(
    (data) => Boolean(data.email) || Boolean(data.phone),
    {
      error: 'Indiquez au moins un e-mail ou un téléphone pour être recontacté',
      path: ['email'],
    },
  );

/**
 * Field names a public caller must never send, refused by name.
 *
 * Zod strips unknown keys by default, so without this an enquiry carrying
 * `internal_margin` would be silently accepted with a 201 — nothing would reach Odoo,
 * but the caller would be told their submission was fine. Refusing tells a mistaken
 * integrator what the contract is, and tells a prober that the boundary is real.
 *
 * Kept in sync with the Odoo controller by an integration test.
 */
export const FORBIDDEN_PUBLIC_FIELDS = [
  'internal_cost',
  'internalCost',
  'purchase_margin',
  'purchaseMargin',
  'internal_margin',
  'internalMargin',
  'supplier_score',
  'supplierScore',
  'internal_commission',
  'internalCommission',
  'negotiation_notes',
  'negotiationNotes',
  'approval_status',
  'approvalStatus',
  'purchase_unit_price',
  'purchaseUnitPrice',
  'gross_margin',
  'grossMargin',
  'net_margin',
  'netMargin',
  'margin_rate',
  'marginRate',
  'cost_total',
  'costTotal',
  'supplier',
  'supplier_id',
  'supplierId',
  'internal_notes',
  'internalNotes',
  'state',
  'responsible_id',
  'responsibleId',
  'company_id',
  'companyId',
] as const;

/**
 * The name of the first internal field found anywhere in a raw body, or null.
 *
 * Walks the whole structure rather than the top level, so a field smuggled inside
 * `contact` is caught too.
 */
export function findForbiddenField(body: unknown): string | null {
  const forbidden = new Set<string>(FORBIDDEN_PUBLIC_FIELDS);

  function walk(node: unknown, depth: number): string | null {
    if (depth > 8 || node === null || typeof node !== 'object') return null;
    if (Array.isArray(node)) {
      for (const item of node) {
        const found = walk(item, depth + 1);
        if (found) return found;
      }
      return null;
    }
    for (const [key, value] of Object.entries(node)) {
      if (forbidden.has(key)) return key;
      const found = walk(value, depth + 1);
      if (found) return found;
    }
    return null;
  }

  return walk(body, 0);
}

export type TradeFormData = z.output<typeof tradeFormSchema>;

export function isBotSubmission(data: TradeFormData): boolean {
  return Boolean(data.website && data.website.trim() !== '');
}

/**
 * Map the validated form onto the gateway input.
 *
 * The honeypot and the idempotency key are dropped: the first is never business data,
 * the second travels as its own argument because it is a transport concern.
 */
export function toTradeInput(data: TradeFormData): TradeOpportunityInput {
  return {
    operationType: data.operationType,
    subject: data.subject,
    ...(data.description !== undefined && { description: data.description }),
    ...(data.requirements !== undefined && { requirements: data.requirements }),
    contact: {
      name: data.contactName,
      ...(data.company !== undefined && { company: data.company }),
      ...(data.email !== undefined && { email: data.email }),
      ...(data.phone !== undefined && { phone: data.phone }),
      ...(data.whatsapp !== undefined && { whatsapp: data.whatsapp }),
      ...(data.contactCountry !== undefined && { country: data.contactCountry }),
    },
    ...(data.originCountry !== undefined && { originCountry: data.originCountry }),
    ...(data.destinationCountry !== undefined && {
      destinationCountry: data.destinationCountry,
    }),
    ...(data.sourceUrl !== undefined && { sourceUrl: data.sourceUrl }),
    ...(data.referrerUrl !== undefined && { referrerUrl: data.referrerUrl }),
  };
}

/** The six steps, in order. */
export type TradeStepId =
  | 'operation'
  | 'subject'
  | 'requirement'
  | 'flow'
  | 'contact'
  | 'review';

export const TRADE_STEPS: ReadonlyArray<TradeStepId> = [
  'operation',
  'subject',
  'requirement',
  'flow',
  'contact',
  'review',
];

export const STEP_LABELS: Readonly<Record<TradeStepId, string>> = {
  operation: 'Type d’opération',
  subject: 'Objet',
  requirement: 'Votre besoin',
  flow: 'Origine et destination',
  contact: 'Vos coordonnées',
  review: 'Récapitulatif',
};

/**
 * Which fields each step owns.
 *
 * Declared as data so "Suivant" validates exactly the current step. Without it, a
 * prospect on step 2 is told their phone number is missing — a field they have not
 * reached yet, which reads as the form being broken.
 */
export const STEP_FIELDS: Readonly<Record<TradeStepId, ReadonlyArray<string>>> = {
  operation: ['operationType'],
  subject: ['subject', 'description'],
  requirement: ['requirements'],
  flow: ['originCountry', 'destinationCountry'],
  contact: ['contactName', 'company', 'email', 'phone', 'whatsapp', 'contactCountry'],
  review: [],
};
