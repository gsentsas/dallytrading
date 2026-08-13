import { describe, expect, it } from 'vitest';
import {
  absoluteUrl,
  activityListJsonLd,
  breadcrumbJsonLd,
  clampDescription,
  faqJsonLd,
  organizationJsonLd,
  pageMetadata,
  serviceJsonLd,
  webSiteJsonLd,
} from './seo';
import { ACTIVITIES } from '@/config/activities';
import { SITE_URL } from '@/config/site';

/**
 * SEO regressions are invisible until traffic drops, so the invariants that matter
 * — one canonical per page, absolute URLs, no invented structured data — are pinned
 * here rather than trusted.
 */

describe('absoluteUrl', () => {
  it('builds an absolute URL from a path', () => {
    expect(absoluteUrl('/contact')).toBe(`${SITE_URL}/contact`);
  });

  it('collapses the root to the bare origin', () => {
    // A trailing slash on the origin would give two canonical spellings of the
    // homepage, splitting its ranking signal.
    expect(absoluteUrl('/')).toBe(SITE_URL);
  });

  it('tolerates a path without a leading slash', () => {
    expect(absoluteUrl('contact')).toBe(`${SITE_URL}/contact`);
  });

  it('never produces a double slash', () => {
    for (const path of ['/', '/contact', 'contact', '/activites/fret-maritime']) {
      expect(absoluteUrl(path).replace(/^https?:\/\//, '')).not.toContain('//');
    }
  });
});

describe('clampDescription', () => {
  it('leaves a short description untouched', () => {
    expect(clampDescription('Fret maritime au Sénégal.')).toBe(
      'Fret maritime au Sénégal.',
    );
  });

  it('collapses whitespace', () => {
    expect(clampDescription('Fret   maritime\n au  Sénégal.')).toBe(
      'Fret maritime au Sénégal.',
    );
  });

  it('truncates at a word boundary', () => {
    // A snippet ending "logisti…" reads as a broken page.
    const long = `${'logistique '.repeat(40)}fin`;
    const result = clampDescription(long);
    expect(result.length).toBeLessThanOrEqual(160);
    expect(result.endsWith('…')).toBe(true);
    expect(result).not.toMatch(/logisti…$/);
  });
});

describe('pageMetadata', () => {
  it('sets exactly one absolute canonical', () => {
    const metadata = pageMetadata({
      title: 'Fret maritime',
      description: 'Conteneur complet et groupage.',
      path: '/activites/fret-maritime',
    });
    expect(metadata.alternates?.canonical).toBe(
      `${SITE_URL}/activites/fret-maritime`,
    );
  });

  it('mirrors the canonical in OpenGraph', () => {
    const metadata = pageMetadata({
      title: 'Contact', description: 'Écrivez-nous.', path: '/contact',
    });
    expect(metadata.openGraph?.url).toBe(`${SITE_URL}/contact`);
    expect(metadata.openGraph?.locale).toBe('fr_FR');
  });

  it('forces noindex when asked, regardless of environment', () => {
    // A tracking result carries a customer's shipment status; it must never be
    // archived, in any environment.
    const metadata = pageMetadata({
      title: 'Suivi', description: 'Suivre une expédition.',
      path: '/tracking', noindex: true,
    });
    expect(metadata.robots).toMatchObject({ index: false, follow: false });
  });

  it('does not index outside production', () => {
    // The test environment is not production, so nothing here may be indexable.
    const metadata = pageMetadata({
      title: 'Accueil', description: 'Import-export.', path: '/',
    });
    expect(metadata.robots).toMatchObject({ index: false });
  });

  it('omits the keywords field rather than emitting an empty array', () => {
    const metadata = pageMetadata({
      title: 'Accueil', description: 'Import-export.', path: '/',
    });
    expect(metadata.keywords).toBeUndefined();
  });
});

describe('organizationJsonLd', () => {
  it('declares the organisation with a stable @id', () => {
    const data = organizationJsonLd();
    expect(data['@type']).toBe('Organization');
    expect(data['@id']).toBe(`${SITE_URL}/#organization`);
    expect(data.url).toBe(SITE_URL);
  });

  it('asserts no fact nobody supplied', () => {
    // Structured data is a machine-readable claim. Asserting a founding date or a
    // rating that was never provided would be inventing a credential.
    const data = organizationJsonLd();
    for (const invented of [
      'foundingDate', 'numberOfEmployees', 'aggregateRating', 'award',
      'taxID', 'vatID', 'duns',
    ]) {
      expect(data[invented]).toBeUndefined();
    }
  });

  it('omits contact points when nothing is configured', () => {
    // No phone or e-mail is configured in the test environment, so no ContactPoint
    // must be asserted.
    const data = organizationJsonLd();
    expect(data.contactPoint).toBeUndefined();
  });
});

describe('webSiteJsonLd', () => {
  it('points at the organisation by reference', () => {
    const data = webSiteJsonLd();
    expect(data['@type']).toBe('WebSite');
    expect(data.publisher).toEqual({ '@id': `${SITE_URL}/#organization` });
  });
});

describe('serviceJsonLd', () => {
  it('describes an activity as a Service provided by the organisation', () => {
    const activity = ACTIVITIES[0];
    expect(activity).toBeDefined();
    if (!activity) return;

    const data = serviceJsonLd(activity);
    expect(data['@type']).toBe('Service');
    expect(data.name).toBe(activity.title);
    expect(data.url).toBe(`${SITE_URL}/activites/${activity.slug}`);
    expect(data.provider).toEqual({ '@id': `${SITE_URL}/#organization` });
  });

  it('produces valid JSON for every activity', () => {
    for (const activity of ACTIVITIES) {
      expect(() => JSON.stringify(serviceJsonLd(activity))).not.toThrow();
    }
  });
});

describe('breadcrumbJsonLd', () => {
  it('numbers positions from one and absolutises hrefs', () => {
    const data = breadcrumbJsonLd([
      { label: 'Accueil', href: '/' },
      { label: 'Nos activités', href: '/activites' },
      { label: 'Fret Maritime' },
    ]);
    const items = data.itemListElement as Array<Record<string, unknown>>;
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ position: 1, item: SITE_URL });
    expect(items[1]).toMatchObject({ position: 2, item: `${SITE_URL}/activites` });
    // The current page carries no item URL: it is where the user already is.
    expect(items[2]?.item).toBeUndefined();
  });
});

describe('faqJsonLd', () => {
  it('returns null for an empty FAQ', () => {
    // Emitting an empty FAQPage would claim a structure the page does not have.
    expect(faqJsonLd([])).toBeNull();
  });

  it('maps questions to answers', () => {
    const data = faqJsonLd([
      { question: 'Quel délai ?', answer: 'Cela dépend du port de départ.' },
    ]);
    expect(data?.['@type']).toBe('FAQPage');
    const entries = data?.mainEntity as Array<Record<string, unknown>>;
    expect(entries[0]).toMatchObject({ '@type': 'Question', name: 'Quel délai ?' });
  });

  it('only marks up content the pages actually render', () => {
    // Every activity's FAQ is rendered in <details> elements, which keep the text in
    // the DOM. That is what makes this markup legitimate rather than cloaking.
    for (const activity of ACTIVITIES) {
      const data = faqJsonLd(activity.faq);
      if (activity.faq.length === 0) {
        expect(data).toBeNull();
      } else {
        expect((data?.mainEntity as unknown[]).length).toBe(activity.faq.length);
      }
    }
  });
});

describe('activityListJsonLd', () => {
  it('lists every activity with an absolute URL', () => {
    const data = activityListJsonLd();
    const items = data.itemListElement as Array<Record<string, unknown>>;
    expect(items).toHaveLength(ACTIVITIES.length);
    for (const item of items) {
      expect(String(item.url).startsWith(`${SITE_URL}/activites/`)).toBe(true);
    }
  });
});
