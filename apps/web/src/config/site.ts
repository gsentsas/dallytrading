/**
 * Site configuration.
 *
 * Everything a non-developer might need to change — phone numbers, addresses,
 * opening hours, social profiles — lives here and is read from the environment.
 *
 * ## Why nothing is hardcoded to a plausible-looking value
 *
 * A placeholder phone number on a live contact page is worse than no phone
 * number: a customer dials it, reaches nobody, and concludes the company is not
 * real. So every channel is **optional**, and the UI omits any channel that is
 * not configured rather than displaying a fake one. The WhatsApp button does not
 * render at all without a number.
 *
 * These values are public by nature (they belong on a contact page), so they use
 * `NEXT_PUBLIC_` and are safe in a client component. No secret belongs here.
 */

/** Absolute site origin, no trailing slash. */
export const SITE_URL = (
  process.env.NEXT_PUBLIC_SITE_URL ?? 'https://dallytrading.com'
).replace(/\/+$/, '');

export const BRAND = {
  name: 'DallyTrading',
  /** The wordmark, as it appears in the logo. */
  wordmark: { first: 'DALLY', second: 'TRADING' },
  /** The signature line under the wordmark. */
  signature: 'Import • Export • Logistics • Solutions',
  legalName: 'DallyTrading',
  tagline:
    'Votre partenaire pour le commerce, l’import-export et la logistique',
} as const;

/** An empty string means "not configured": the UI omits the channel. */
function optional(value: string | undefined): string | null {
  const trimmed = (value ?? '').trim();
  return trimmed === '' ? null : trimmed;
}

/**
 * Reduce a phone number to digits, for `tel:` and `wa.me` links.
 *
 * `wa.me` refuses anything but digits — no `+`, no spaces — and getting this
 * wrong produces a WhatsApp link that silently opens an empty chat.
 */
export function toDialable(value: string | null): string | null {
  if (!value) return null;
  const digits = value.replace(/\D/g, '');
  return digits.length >= 8 ? digits : null;
}

export const CONTACT = {
  /** Display form, e.g. "+221 77 000 00 00". */
  phone: optional(process.env.NEXT_PUBLIC_CONTACT_PHONE),
  /** WhatsApp number; falls back to the phone number when not set separately. */
  whatsapp:
    optional(process.env.NEXT_PUBLIC_CONTACT_WHATSAPP) ??
    optional(process.env.NEXT_PUBLIC_CONTACT_PHONE),
  email: optional(process.env.NEXT_PUBLIC_CONTACT_EMAIL),
  addressLines: (process.env.NEXT_PUBLIC_CONTACT_ADDRESS ?? '')
    .split('|')
    .map((line) => line.trim())
    .filter(Boolean),
  city: optional(process.env.NEXT_PUBLIC_CONTACT_CITY) ?? 'Dakar',
  country: optional(process.env.NEXT_PUBLIC_CONTACT_COUNTRY) ?? 'Sénégal',
  countryCode: 'SN',
  /** Free text, e.g. "Lundi – Vendredi : 8h30 – 18h00". */
  hours: (process.env.NEXT_PUBLIC_CONTACT_HOURS ?? '')
    .split('|')
    .map((line) => line.trim())
    .filter(Boolean),
} as const;

export const SOCIALS = [
  { label: 'LinkedIn', href: optional(process.env.NEXT_PUBLIC_SOCIAL_LINKEDIN) },
  { label: 'Facebook', href: optional(process.env.NEXT_PUBLIC_SOCIAL_FACEBOOK) },
  { label: 'Instagram', href: optional(process.env.NEXT_PUBLIC_SOCIAL_INSTAGRAM) },
].filter((entry): entry is { label: string; href: string } => entry.href !== null);

/**
 * Whether this deployment may be indexed.
 *
 * Gated on the environment, not hardcoded: a staging copy indexed by Google
 * competes with production for the same keywords and is very hard to undo.
 */
export const INDEXABLE =
  (process.env.NEXT_PUBLIC_ENVIRONMENT ?? process.env.ENVIRONMENT ?? 'development') ===
  'production';

/** Primary calls to action, in the order the specification prioritises them. */
export const CTA = {
  quote: { href: '/devis', label: 'Demander un devis' },
  contact: { href: '/contact', label: 'Parler à un conseiller' },
  tracking: { href: '/tracking', label: 'Suivre mon expédition' },
} as const;

/**
 * SEN CONTAINERS.
 *
 * A commercial partner DallyTrading represents in Senegal. Content only — there
 * is deliberately no model, no API, no CRM link and no technical dependency of
 * any kind. If this ever needs to become a business object, it is a plain
 * `res.partner` like any other partner.
 *
 * Kept secondary to the DallyTrading brand throughout the site (§35).
 */
export const PARTNER_SEN_CONTAINERS = {
  name: 'SEN CONTAINERS',
  role: 'Représentation au Sénégal',
  summary:
    'DallyTrading assure la représentation et la gestion des activités de ' +
    'SEN CONTAINERS au Sénégal, et accompagne les clients dans leurs opérations ' +
    'de transport et de logistique.',
} as const;
