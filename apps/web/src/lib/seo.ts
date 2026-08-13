/**
 * SEO helpers: metadata and structured data.
 *
 * ## Two rules this file enforces
 *
 * 1. **Canonical URLs are absolute and built from one place.** Two URLs serving the
 *    same page split its ranking signal between them, and the usual causes are a
 *    stray trailing slash or a mixed http/https origin.
 *
 * 2. **Indexing is gated on the environment.** A staging copy indexed by Google
 *    competes with production for the same keywords and is slow and painful to
 *    undo. `INDEXABLE` is false unless the deployment declares itself production.
 */

import type { Metadata } from 'next';
import { BRAND, CONTACT, INDEXABLE, SITE_URL, SOCIALS } from '@/config/site';
import { ACTIVITIES, type Activity } from '@/config/activities';

/** Absolute URL for a site-relative path. */
export function absoluteUrl(path: string): string {
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${SITE_URL}${clean === '/' ? '' : clean}`;
}

/**
 * Truncate a description to a length search engines actually display.
 *
 * Around 160 characters. Cutting at a word boundary rather than mid-word, because
 * a snippet ending in "logisti…" reads as a broken page.
 */
export function clampDescription(text: string, max = 158): string {
  const collapsed = text.replace(/\s+/g, ' ').trim();
  if (collapsed.length <= max) return collapsed;
  const cut = collapsed.slice(0, max);
  const lastSpace = cut.lastIndexOf(' ');
  return `${(lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

/**
 * Build page metadata.
 *
 * @param noindex Force exclusion regardless of environment — for pages that must
 *   never be indexed even in production, such as a tracking result carrying a
 *   customer's shipment status.
 */
export function pageMetadata({
  title,
  description,
  path,
  keywords,
  noindex = false,
}: {
  title: string;
  description: string;
  path: string;
  keywords?: ReadonlyArray<string>;
  noindex?: boolean;
}): Metadata {
  const url = absoluteUrl(path);
  const clamped = clampDescription(description);
  const indexable = INDEXABLE && !noindex;

  return {
    title,
    description: clamped,
    ...(keywords && keywords.length > 0 ? { keywords: [...keywords] } : {}),
    alternates: { canonical: url },
    robots: {
      index: indexable,
      follow: indexable,
      googleBot: { index: indexable, follow: indexable },
    },
    openGraph: {
      type: 'website',
      locale: 'fr_FR',
      siteName: BRAND.name,
      url,
      title,
      description: clamped,
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description: clamped,
    },
  };
}

// ─── Structured data ─────────────────────────────────────────────────
//
// Types are hand-written rather than pulled from a schema.org package: the
// vocabulary is large, we use a handful of types, and a dependency for three
// object literals is not worth the supply-chain surface.

type JsonLdValue = string | number | boolean | JsonLdObject | JsonLdValue[];
export interface JsonLdObject {
  [key: string]: JsonLdValue | undefined;
}

/**
 * The organisation itself.
 *
 * Deliberately absent: `foundingDate`, `numberOfEmployees`, `award`, `aggregateRating`.
 * Structured data is a machine-readable assertion, and asserting a fact nobody
 * supplied would be inventing a credential.
 */
export function organizationJsonLd(): JsonLdObject {
  const sameAs = SOCIALS.map((social) => social.href);

  const contactPoint: JsonLdObject[] = [];
  if (CONTACT.phone || CONTACT.email) {
    contactPoint.push({
      '@type': 'ContactPoint',
      contactType: 'customer service',
      areaServed: CONTACT.countryCode,
      availableLanguage: ['fr', 'en'],
      ...(CONTACT.phone ? { telephone: CONTACT.phone } : {}),
      ...(CONTACT.email ? { email: CONTACT.email } : {}),
    });
  }

  const address: JsonLdObject = {
    '@type': 'PostalAddress',
    addressCountry: CONTACT.countryCode,
    addressLocality: CONTACT.city,
    ...(CONTACT.addressLines.length > 0
      ? { streetAddress: CONTACT.addressLines.join(', ') }
      : {}),
  };

  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    '@id': `${SITE_URL}/#organization`,
    name: BRAND.name,
    legalName: BRAND.legalName,
    url: SITE_URL,
    description: BRAND.tagline,
    slogan: BRAND.signature,
    address,
    ...(contactPoint.length > 0 ? { contactPoint } : {}),
    ...(sameAs.length > 0 ? { sameAs } : {}),
    knowsAbout: [
      'Import-export',
      'Logistique',
      'Fret maritime',
      'Fret aérien',
      'Transport de véhicules',
      'Groupage',
      'Commerce international',
      'Trading',
      'Sourcing',
      'Agrobusiness',
    ],
  };
}

/** The site, so a search engine can attribute pages to it. */
export function webSiteJsonLd(): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    '@id': `${SITE_URL}/#website`,
    url: SITE_URL,
    name: BRAND.name,
    inLanguage: 'fr-FR',
    publisher: { '@id': `${SITE_URL}/#organization` },
  };
}

/** One activity, as an offered service. */
export function serviceJsonLd(activity: Activity): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'Service',
    '@id': `${absoluteUrl(`/activites/${activity.slug}`)}#service`,
    name: activity.title,
    description: clampDescription(activity.summary, 300),
    serviceType: activity.label,
    url: absoluteUrl(`/activites/${activity.slug}`),
    provider: { '@id': `${SITE_URL}/#organization` },
    areaServed: {
      '@type': 'Country',
      name: CONTACT.country,
    },
    ...(activity.includes.length > 0
      ? {
          hasOfferCatalog: {
            '@type': 'OfferCatalog',
            name: activity.title,
            itemListElement: activity.includes.map((item) => ({
              '@type': 'Offer',
              itemOffered: { '@type': 'Service', name: item },
            })),
          },
        }
      : {}),
  };
}

/** Breadcrumb trail, mirroring the visible one. */
export function breadcrumbJsonLd(
  trail: ReadonlyArray<{ label: string; href?: string }>,
): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: trail.map((entry, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: entry.label,
      ...(entry.href ? { item: absoluteUrl(entry.href) } : {}),
    })),
  };
}

/**
 * FAQ structured data.
 *
 * Only emitted when the questions and answers are genuinely on the page: marking
 * up content a visitor cannot see is cloaking, and it is penalised.
 */
export function faqJsonLd(
  faq: ReadonlyArray<{ question: string; answer: string }>,
): JsonLdObject | null {
  if (faq.length === 0) return null;
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faq.map((entry) => ({
      '@type': 'Question',
      name: entry.question,
      acceptedAnswer: { '@type': 'Answer', text: entry.answer },
    })),
  };
}

/** The activity list, so the hub page describes its own contents. */
export function activityListJsonLd(): JsonLdObject {
  return {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: 'Activités DallyTrading',
    itemListElement: ACTIVITIES.map((activity, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: activity.title,
      url: absoluteUrl(`/activites/${activity.slug}`),
    })),
  };
}
