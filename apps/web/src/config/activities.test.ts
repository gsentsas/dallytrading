import { describe, expect, it } from 'vitest';
import {
  ACTIVITIES,
  activityHref,
  activityQuoteHref,
  featuredActivities,
  findActivity,
} from './activities';

/**
 * The activity configuration drives the navigation, eleven indexed URLs, the sitemap
 * and the JSON-LD. A mistake here is not a typo, it is a broken URL or a duplicated
 * canonical — so these tests pin the invariants rather than the prose.
 */

describe('ACTIVITIES', () => {
  it('covers the eleven activities the brief lists', () => {
    expect(ACTIVITIES).toHaveLength(11);
  });

  it('has unique slugs', () => {
    // A duplicate slug would make one page unreachable and give two activities the
    // same canonical URL.
    const slugs = ACTIVITIES.map((activity) => activity.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
  });

  it('uses URL-safe slugs', () => {
    for (const activity of ACTIVITIES) {
      expect(activity.slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
    }
  });

  it('uses service codes in the format Odoo enforces', () => {
    // dally.service.type restricts codes to lowercase, digits and underscore. A
    // divergence would lose the pre-selection and be rejected on submission.
    for (const activity of ACTIVITIES) {
      expect(activity.serviceCode).toMatch(/^[a-z0-9_]+$/);
    }
  });

  it('maps every activity to a service seeded by dally_core', () => {
    const seeded = new Set([
      'import_export', 'logistics', 'freight_sea', 'freight_air',
      'freight_vehicle', 'freight_groupage', 'trade', 'sourcing',
      'ecommerce', 'agrobusiness', 'business_solutions', 'other',
    ]);
    for (const activity of ACTIVITIES) {
      expect(seeded.has(activity.serviceCode)).toBe(true);
    }
  });

  it('gives every activity the content each page renders', () => {
    for (const activity of ACTIVITIES) {
      expect(activity.label.length).toBeGreaterThan(2);
      expect(activity.title.length).toBeGreaterThan(2);
      expect(activity.summary.length).toBeGreaterThan(40);
      expect(activity.intro.length).toBeGreaterThan(80);
      expect(activity.includes.length).toBeGreaterThanOrEqual(4);
      expect(activity.audience.length).toBeGreaterThanOrEqual(1);
      expect(activity.keywords.length).toBeGreaterThanOrEqual(2);
    }
  });

  it('keeps summaries short enough to survive a meta description', () => {
    // Search engines display roughly 160 characters. A summary far beyond that is
    // truncated in a snippet, and truncation mid-sentence reads as a broken page.
    for (const activity of ACTIVITIES) {
      expect(activity.summary.length).toBeLessThanOrEqual(200);
    }
  });

  it('gives every FAQ entry a real answer', () => {
    for (const activity of ACTIVITIES) {
      for (const entry of activity.faq) {
        expect(entry.question.endsWith('?')).toBe(true);
        expect(entry.answer.length).toBeGreaterThan(60);
      }
    }
  });

  it('states no invented figures', () => {
    // No founding year, headcount, client count or tonnage was ever supplied.
    // Asserting one on the company's own site is a false statement its salespeople
    // then have to defend, so the copy must contain none.
    const forbidden =
      /\b(\d{1,3})\s*(ans d’expérience|ans d'expérience|clients|collaborateurs|salariés|conteneurs\/an|tonnes\/an)\b/i;
    for (const activity of ACTIVITIES) {
      const prose = [
        activity.summary,
        activity.intro,
        ...activity.includes,
        ...activity.audience,
        ...activity.faq.map((entry) => `${entry.question} ${entry.answer}`),
      ].join(' ');
      expect(prose).not.toMatch(forbidden);
    }
  });

  it('features between four and eight activities on the homepage', () => {
    // Fewer looks thin for a multisector company; more turns the homepage into a
    // list nobody reads.
    const featured = featuredActivities();
    expect(featured.length).toBeGreaterThanOrEqual(4);
    expect(featured.length).toBeLessThanOrEqual(8);
  });
});

describe('findActivity', () => {
  it('resolves a known slug', () => {
    expect(findActivity('fret-maritime')?.title).toBe('Fret Maritime');
  });

  it('returns undefined for an unknown slug', () => {
    // The activity route relies on this to trigger a 404 rather than render an
    // empty shell that a search engine would then index.
    expect(findActivity('inexistant')).toBeUndefined();
    expect(findActivity('')).toBeUndefined();
  });
});

describe('href helpers', () => {
  it('builds activity URLs under /activites', () => {
    for (const activity of ACTIVITIES) {
      expect(activityHref(activity)).toBe(`/activites/${activity.slug}`);
    }
  });

  it('builds a quote link carrying the service code', () => {
    const activity = findActivity('fret-aerien');
    expect(activity).toBeDefined();
    if (!activity) return;
    expect(activityQuoteHref(activity)).toBe('/devis?service=freight_air');
  });

  it('encodes the service code', () => {
    // Codes are constrained to [a-z0-9_], so nothing needs escaping today. The
    // encoding stays so that relaxing the constraint cannot silently produce a
    // malformed URL.
    const activity = findActivity('solutions-entreprises');
    expect(activity).toBeDefined();
    if (!activity) return;
    expect(activityQuoteHref(activity)).not.toContain(' ');
  });
});
