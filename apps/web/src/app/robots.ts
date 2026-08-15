import type { MetadataRoute } from 'next';
import { INDEXABLE } from '@/config/site';
import { absoluteUrl } from '@/lib/seo';

/**
 * robots.txt
 *
 * ## Non-production deployments disallow everything
 *
 * A staging copy indexed by Google competes with production for the same keywords,
 * splits its ranking signal, and is slow and painful to undo. `INDEXABLE` is false
 * unless the deployment declares itself production, and this file honours that.
 *
 * ## What production disallows, and why
 *
 * * `/api/` — endpoints, not pages. Nothing to index, and crawling them wastes
 *   budget on responses marked `no-store`.
 * * `/tracking` — a tracking result carries a customer's shipment status. It must
 *   never be archived by a search engine, and a crawler walking it would also burn
 *   the rate limit that protects it.
 * * `/espace-client` — private by construction; a crawler only ever gets a redirect
 *   to the login page, so indexing it produces a misleading result for the brand's
 *   own name.
 * * `/connexion` — an indexed login page is a ready-made phishing target: it ranks
 *   for the company name and trains customers to reach their account through search
 *   results rather than a known URL.
 *
 * `robots.txt` is a request, not an access control: it keeps well-behaved crawlers
 * out, and nothing else. The tracking endpoint's real protection is the
 * unpredictable token it requires.
 */
export default function robots(): MetadataRoute.Robots {
  if (!INDEXABLE) {
    return {
      rules: [{ userAgent: '*', disallow: '/' }],
    };
  }

  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        disallow: ['/api/', '/tracking', '/espace-client', '/connexion'],
      },
    ],
    sitemap: absoluteUrl('/sitemap.xml'),
    host: absoluteUrl('/'),
  };
}
