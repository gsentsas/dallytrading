import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import {
  Breadcrumbs,
  Card,
  CheckList,
  Container,
  CtaLink,
  CtaRow,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import {
  ACTIVITIES,
  activityHref,
  activityQuoteHref,
  findActivity,
} from '@/config/activities';
import {
  breadcrumbJsonLd,
  faqJsonLd,
  pageMetadata,
  serviceJsonLd,
  type JsonLdObject,
} from '@/lib/seo';

/**
 * One page per activity, generated from the editorial configuration.
 *
 * `generateStaticParams` makes all eleven static at build time: they are the same
 * for every visitor, so rendering them on demand would spend a server round trip on
 * content that never changes between deploys. It also means these pages stay up if
 * Odoo is down — they carry no ERP dependency, only a deep link to the quote form.
 */

export function generateStaticParams() {
  return ACTIVITIES.map((activity) => ({ slug: activity.slug }));
}

/** An unknown slug must 404, not render an empty shell that Google then indexes. */
export const dynamicParams = false;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const activity = findActivity(slug);
  if (!activity) {
    return pageMetadata({
      title: 'Activité introuvable',
      description: 'Cette activité n’existe pas ou a été renommée.',
      path: `/activites/${slug}`,
      noindex: true,
    });
  }

  return pageMetadata({
    title: `${activity.title} — DallyTrading`,
    description: activity.summary,
    path: activityHref(activity),
    keywords: activity.keywords,
  });
}

export default async function ActivityPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const activity = findActivity(slug);
  if (!activity) {
    notFound();
  }

  const trail = [
    { label: 'Accueil', href: '/' },
    { label: 'Nos activités', href: '/activites' },
    { label: activity.label },
  ];

  // Three other activities to suggest. Adjacent rather than random, so the ordering
  // is stable between builds — a page whose "see also" changes on every deploy
  // looks broken to a returning visitor.
  const index = ACTIVITIES.findIndex((entry) => entry.slug === activity.slug);
  const related = [1, 2, 3]
    .map((offset) => ACTIVITIES[(index + offset) % ACTIVITIES.length])
    .filter((entry): entry is (typeof ACTIVITIES)[number] => entry !== undefined);

  const structuredData: JsonLdObject[] = [
    serviceJsonLd(activity),
    breadcrumbJsonLd(trail),
  ];
  const faq = faqJsonLd(activity.faq);
  if (faq) {
    structuredData.push(faq);
  }

  return (
    <main id="contenu">
      {/* ─── Header ──────────────────────────────────────────────────── */}
      <section
        aria-labelledby="activite-titre"
        className="relative overflow-hidden bg-navy-700 text-white"
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-20 -right-10 h-56 w-96 rotate-6 rounded-[100%] bg-gradient-to-r from-leaf/25 to-leaf-light/10 blur-2xl"
        />
        <Container className="relative py-12 sm:py-16">
          <div className="[&_a]:text-navy-100 [&_a:hover]:text-green-400 [&_span]:text-white">
            <Breadcrumbs trail={trail} />
          </div>
          <p className="dally-signature mt-6 text-xs font-semibold text-green-400">
            Nos activités
          </p>
          <h1
            id="activite-titre"
            className="mt-3 max-w-3xl text-3xl font-bold leading-tight sm:text-4xl"
          >
            {activity.title}
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-navy-100">
            {activity.summary}
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <CtaLink href={activityQuoteHref(activity)}>
              Demander un devis
            </CtaLink>
            <CtaLink href="/contact" variant="onNavy">
              Parler à un conseiller
            </CtaLink>
          </div>
        </Container>
      </section>

      {/* ─── What it covers ─────────────────────────────────────────── */}
      <Section labelledBy="prestation-titre" tone="white">
        <Container>
          <div className="grid gap-12 lg:grid-cols-2">
            <div>
              <SectionHeading
                id="prestation-titre"
                title="Ce que nous prenons en charge"
              />
              <p className="mt-6 leading-relaxed text-mist-700">
                {activity.intro}
              </p>
              <div className="mt-8">
                <CheckList items={activity.includes} />
              </div>
            </div>

            <aside
              aria-labelledby="pour-qui-titre"
              className="h-fit rounded-2xl border border-mist-200 bg-mist-50 p-7"
            >
              <h2
                id="pour-qui-titre"
                className="text-lg font-bold text-navy-800"
              >
                Pour qui ?
              </h2>
              <span aria-hidden="true" className="dally-swoosh mt-3 block w-12" />
              <ul className="mt-5 space-y-4">
                {activity.audience.map((entry) => (
                  <li key={entry} className="text-sm leading-relaxed text-mist-700">
                    {entry}
                  </li>
                ))}
              </ul>

              <div className="mt-7 border-t border-mist-200 pt-6">
                <p className="text-sm text-mist-600">
                  Vous vous reconnaissez ? Une demande prend quelques minutes et vous
                  recevez une référence de suivi immédiatement.
                </p>
                <CtaLink
                  href={activityQuoteHref(activity)}
                  className="mt-4 w-full"
                >
                  Demander un devis
                </CtaLink>
              </div>
            </aside>
          </div>
        </Container>
      </Section>

      {/* ─── FAQ ────────────────────────────────────────────────────── */}
      {activity.faq.length > 0 && (
        <Section labelledBy="faq-titre" tone="mist">
          <Container size="narrow">
            <SectionHeading
              id="faq-titre"
              eyebrow="Questions fréquentes"
              title={`${activity.title} : ce qu’on nous demande`}
            />
            {/* <details> gives a working disclosure with correct semantics and no
                JavaScript, and the content stays in the DOM for search engines —
                which is what makes the FAQPage markup legitimate rather than
                cloaking. */}
            <div className="mt-10 divide-y divide-mist-200 rounded-xl border border-mist-200 bg-white">
              {activity.faq.map((entry) => (
                <details key={entry.question} className="group p-6">
                  <summary className="cursor-pointer list-none font-semibold text-navy-700 marker:content-none">
                    <span className="flex items-start justify-between gap-4">
                      {entry.question}
                      <span
                        aria-hidden="true"
                        className="mt-0.5 shrink-0 text-green-700 transition-transform group-open:rotate-45"
                      >
                        +
                      </span>
                    </span>
                  </summary>
                  <p className="mt-4 leading-relaxed text-mist-600">
                    {entry.answer}
                  </p>
                </details>
              ))}
            </div>
          </Container>
        </Section>
      )}

      {/* ─── Related ────────────────────────────────────────────────── */}
      <Section labelledBy="associees-titre" tone="white">
        <Container>
          <SectionHeading
            id="associees-titre"
            title="Autres activités"
            lead="Nos métiers se combinent : une même opération mobilise souvent plusieurs d’entre eux."
          />
          <div className="mt-10 grid gap-6 sm:grid-cols-3">
            {related.map((entry) => (
              <Card
                key={entry.slug}
                href={activityHref(entry)}
                title={entry.title}
                footer={
                  <span className="text-sm font-semibold text-green-700">
                    En savoir plus <span aria-hidden="true">→</span>
                  </span>
                }
              >
                {entry.summary}
              </Card>
            ))}
          </div>
          <p className="mt-8 text-sm text-mist-600">
            <Link href="/activites" className="font-semibold text-green-700 hover:underline">
              Voir les onze activités
            </Link>
          </p>
        </Container>
      </Section>

      {/* ─── Closing CTA ────────────────────────────────────────────── */}
      <Section labelledBy="activite-cta" tone="navy">
        <Container>
          <h2 id="activite-cta" className="text-2xl font-bold sm:text-3xl">
            Une question sur {activity.title.toLowerCase()} ?
          </h2>
          <p className="mt-4 max-w-2xl leading-relaxed text-navy-100">
            Décrivez votre besoin : nous ne demandons que les informations utiles à ce
            service, et nous revenons vers vous avec une réponse chiffrée.
          </p>
          <CtaRow onDark className="mt-8" />
        </Container>
      </Section>

      <JsonLd data={structuredData} />
    </main>
  );
}
