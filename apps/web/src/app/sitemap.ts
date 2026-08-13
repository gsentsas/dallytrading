import type { MetadataRoute } from 'next';
import { ACTIVITIES } from '@/config/activities';
import { INDEXABLE } from '@/config/site';
import { absoluteUrl } from '@/lib/seo';

/**
 * Sitemap.
 *
 * Generated from the same activity configuration the pages use, so a new activity
 * appears here automatically. A hand-maintained sitemap drifts within weeks, and a
 * sitemap listing pages that no longer exist damages trust in the whole file.
 *
 * ## What is deliberately absent
 *
 * * `/tracking` — carries a customer's shipment status. It is `noindex`, and listing
 *   it in a sitemap while asking robots not to index it is a contradiction crawlers
 *   report as an error.
 * * `/devis` and `/contact` are included: they are genuine landing pages people
 *   search for.
 * * Non-production deployments return an **empty** sitemap. Serving a staging
 *   sitemap full of staging URLs is how a staging copy ends up competing with
 *   production for the same keywords.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  if (!INDEXABLE) {
    return [];
  }

  // A single timestamp for the whole build: pages change when the site is deployed,
  // and per-page `new Date()` would claim every page changed at a slightly different
  // moment, which is simply false.
  const lastModified = new Date();

  return [
    {
      url: absoluteUrl('/'),
      lastModified,
      changeFrequency: 'weekly',
      priority: 1,
    },
    {
      url: absoluteUrl('/activites'),
      lastModified,
      changeFrequency: 'monthly',
      priority: 0.9,
    },
    {
      url: absoluteUrl('/devis'),
      lastModified,
      changeFrequency: 'monthly',
      priority: 0.9,
    },
    {
      // A conversion page with its own form and FAQ, ranked alongside /devis rather
      // than under the activity that describes the service.
      url: absoluteUrl('/sourcing'),
      lastModified,
      changeFrequency: 'monthly',
      priority: 0.9,
    },
    {
      // Same reasoning as /sourcing: a conversion page in its own right, distinct
      // from /activites/commerce-trading which serves the informational intent.
      url: absoluteUrl('/trading'),
      lastModified,
      changeFrequency: 'monthly',
      priority: 0.9,
    },
    {
      url: absoluteUrl('/a-propos'),
      lastModified,
      changeFrequency: 'yearly',
      priority: 0.6,
    },
    {
      url: absoluteUrl('/contact'),
      lastModified,
      changeFrequency: 'yearly',
      priority: 0.7,
    },
    ...ACTIVITIES.map((activity) => ({
      url: absoluteUrl(`/activites/${activity.slug}`),
      lastModified,
      changeFrequency: 'monthly' as const,
      // Featured activities are the commercial priorities; the rest still rank.
      priority: activity.featured ? 0.8 : 0.6,
    })),
  ];
}
