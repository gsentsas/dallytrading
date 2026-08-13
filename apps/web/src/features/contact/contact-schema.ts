/**
 * Validation of the contact form.
 *
 * Kept separate from the quote schema on purpose. A contact message and a quote
 * request are different objects with different obligations: a quote needs a service
 * and route details, a contact needs only a way to reply. Folding them into one
 * schema would mean either asking a visitor for a port of loading to say hello, or
 * loosening the quote rules until they stop protecting anything.
 *
 * A contact message becomes a `crm.lead` through the existing `createLead` gateway
 * method — no new Odoo endpoint, and no change to the quote pipeline.
 */

import { z } from 'zod';
import type { LeadInput } from '@/services/odoo/types';

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

/**
 * Subjects offered on the form.
 *
 * Each maps to a `dally.service.type.code` that ships with `dally_core`, so a
 * contact message lands in the CRM already attributed to the right activity —
 * which is what lets the sales team route it without reading it first.
 *
 * `other` is the fallback and always exists in the seeded catalogue.
 */
export const CONTACT_SUBJECTS = [
  { value: 'other', label: 'Question générale' },
  { value: 'import_export', label: 'Import & Export' },
  { value: 'freight_sea', label: 'Fret maritime' },
  { value: 'freight_air', label: 'Fret aérien' },
  { value: 'freight_vehicle', label: 'Transport de véhicules' },
  { value: 'freight_groupage', label: 'Groupage' },
  { value: 'logistics', label: 'Logistique & Transport' },
  { value: 'sourcing', label: 'Sourcing international' },
  { value: 'trade', label: 'Commerce & Trading' },
  { value: 'agrobusiness', label: 'Agrobusiness' },
  { value: 'business_solutions', label: 'Solutions entreprises' },
] as const;

const SUBJECT_CODES = CONTACT_SUBJECTS.map((subject) => subject.value);

export const contactFormSchema = z
  .object({
    requestUuid: z
      .string({ error: 'Identifiant de demande manquant' })
      .trim()
      .refine((value) => UUID_RE.test(value), 'Identifiant de demande invalide'),

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

    /** Restricted to the known codes: Odoo rejects anything else anyway. */
    subject: z
      .string()
      .trim()
      .refine(
        (value) => SUBJECT_CODES.includes(value as (typeof SUBJECT_CODES)[number]),
        'Sujet invalide',
      )
      .default('other'),

    message: z
      .string({ error: 'Le message est obligatoire' })
      .trim()
      .min(10, 'Merci de détailler un peu votre demande (10 caractères minimum)')
      .max(20_000),

    sourceUrl: optionalText(500),
    referrerUrl: optionalText(500),

    /** Honeypot — hidden from users; a value means an automated submission. */
    website: z.string().max(200).optional(),
  })
  .refine((data) => Boolean(data.email ?? data.phone), {
    message: 'Indiquez au moins un e-mail ou un téléphone',
    path: ['email'],
  });

export type ContactFormData = z.output<typeof contactFormSchema>;

export function isBotSubmission(data: ContactFormData): boolean {
  return typeof data.website === 'string' && data.website.trim() !== '';
}

/** Human label for a subject code, for the confirmation screen and the CRM. */
export function subjectLabel(value: string): string {
  return (
    CONTACT_SUBJECTS.find((subject) => subject.value === value)?.label ??
    'Question générale'
  );
}

/**
 * Map validated data onto the gateway's lead input.
 *
 * The subject becomes the lead's service, so the message arrives in the CRM already
 * attributed. The honeypot and the idempotency key are dropped: the first is
 * anti-spam plumbing, the second describes the call rather than the lead.
 */
export function toLeadInput(data: ContactFormData): LeadInput {
  return {
    serviceCode: data.subject,
    lastName: data.lastName,
    ...(data.firstName !== undefined && { firstName: data.firstName }),
    ...(data.companyName !== undefined && { companyName: data.companyName }),
    ...(data.email !== undefined && { email: data.email }),
    ...(data.phone !== undefined && { phone: data.phone }),
    ...(data.whatsapp !== undefined && { whatsapp: data.whatsapp }),
    ...(data.city !== undefined && { city: data.city }),
    message: data.message,
    ...(data.sourceUrl !== undefined && { sourceUrl: data.sourceUrl }),
    // The referrer is deliberately NOT forwarded. `crm.lead` has no referrer
    // column, and the nearest candidate — `utmSource` — is what the CRM groups by
    // for attribution reporting. Putting a URL there would corrupt those reports
    // with values that are not campaign sources. The referrer is captured properly
    // on `dally.quote.request`, which has a field for it; a contact message does
    // without rather than dirtying a report.
  };
}
