import type { Metadata } from 'next';
import Link from 'next/link';
import {
  Breadcrumbs,
  CheckList,
  Container,
  CtaLink,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import { TradeForm } from '@/features/trade/TradeForm';
import { TRADE_OPERATION_TYPES } from '@/features/trade/trade-schema';
import {
  breadcrumbJsonLd,
  faqJsonLd,
  pageMetadata,
  type JsonLdObject,
} from '@/lib/seo';
import { CONTACT, SITE_URL } from '@/config/site';

const TRAIL = [
  { label: 'Accueil', href: '/' },
  { label: 'Nos activités', href: '/activites' },
  { label: 'Trading' },
];

/**
 * Distinct from /activites/commerce-trading, on purpose.
 *
 * The activity page explains what commerce and trading are and who they are for — an
 * informational intent. This page asks a prospect to propose an operation — a
 * conversion intent. Two pages targeting the same intent would split the ranking
 * signal and let Google pick one, usually not the one that converts.
 *
 * The separation is enforced in three places: different titles and descriptions here,
 * different H1s, and `requestHref: '/trading'` on the activity so its CTA sends
 * conversion intent to this page rather than competing for it.
 */
export const metadata: Metadata = pageMetadata({
  title: 'Proposer une opération de trading — Négoce, courtage, commission',
  description:
    'Achat-revente, courtage, commission, distribution, import-export ou ' +
    'représentation commerciale : proposez votre opération à DallyTrading et ' +
    'recevez une référence de suivi immédiate.',
  path: '/trading',
  keywords: [
    'proposer une opération de trading',
    'négoce international Sénégal',
    'courtage marchandises Dakar',
    'commission commerciale Sénégal',
    'représentation commerciale Sénégal',
    'achat revente international Sénégal',
  ],
});

export const dynamic = 'force-dynamic';

/**
 * The questions a prospect actually asks before proposing a deal.
 *
 * Nothing here promises a rate, a margin, a threshold or a delay: those are
 * negotiated per operation, and printing a number nobody decided would be quoting a
 * price on a public page.
 */
const FAQ = [
  {
    question: 'Quelle différence entre le négoce et le courtage ?',
    answer:
      'En négoce — l’achat-revente — DallyTrading achète la marchandise et vous la revend : nous portons l’opération et son risque. En courtage, nous rapprochons un acheteur et un vendeur sans jamais acquérir la marchandise, et nous sommes rémunérés pour la mise en relation. Nous précisons notre rôle et notre rémunération dès la proposition.',
  },
  {
    question: 'Comment DallyTrading est-il rémunéré ?',
    answer:
      'Par une marge sur négoce, ou par une commission d’intermédiation, selon le type d’opération. Le mode et le montant sont indiqués dans la proposition : nous n’appliquons pas de taux automatique, chaque opération est chiffrée pour ce qu’elle est.',
  },
  {
    question: 'Faut-il déjà avoir un fournisseur ou un acheteur ?',
    answer:
      'Non. Si vous cherchez un fournisseur, la demande relève plutôt du sourcing. Si vous avez un lot à placer, un besoin à couvrir ou une opération à structurer, elle relève du trading. Si vous hésitez, décrivez votre situation : nous vous orienterons.',
  },
  {
    question: 'Traitez-vous toutes les catégories de produits ?',
    answer:
      'Nous privilégions les produits que nous connaissons et dont nous maîtrisons la chaîne. Soumettez votre opération : nous vous dirons franchement si elle relève de notre périmètre, plutôt que de vous faire attendre.',
  },
  {
    question: 'Quelles informations dois-je fournir à ce stade ?',
    answer:
      'Le type d’opération envisagé, son objet, votre besoin et un moyen de vous joindre. Aucune information commerciale sensible n’est nécessaire pour engager la discussion : les conditions se précisent ensuite, dans un échange direct.',
  },
  {
    question: 'Que se passe-t-il après l’envoi ?',
    answer:
      'Vous recevez immédiatement une référence de suivi. Notre équipe qualifie l’opération, en précise la structure avec vous, puis vous adresse une proposition. Rien n’est engagé avant votre accord explicite.',
  },
];

const STEPS = [
  {
    step: '01',
    title: 'Votre proposition',
    text: 'Vous décrivez le type d’opération et ce que vous cherchez à faire.',
  },
  {
    step: '02',
    title: 'La qualification',
    text: 'Nous vérifions que l’opération relève de notre périmètre et en précisons la structure avec vous.',
  },
  {
    step: '03',
    title: 'Le chiffrage',
    text: 'Nous établissons les conditions : prix, incoterm, délais, et notre rémunération.',
  },
  {
    step: '04',
    title: 'L’exécution',
    text: 'Une fois l’accord conclu, nous coordonnons l’achat, la logistique et le suivi jusqu’au règlement.',
  },
];

export default function TradingPage() {
  const structuredData: JsonLdObject[] = [
    {
      '@context': 'https://schema.org',
      '@type': 'Service',
      '@id': `${SITE_URL}/trading#service`,
      name: 'Opérations de trading',
      description:
        'Achat-revente, courtage, commission, distribution, import-export et ' +
        'représentation commerciale.',
      serviceType: 'Négoce et intermédiation commerciale',
      url: `${SITE_URL}/trading`,
      provider: { '@id': `${SITE_URL}/#organization` },
      areaServed: { '@type': 'Country', name: CONTACT.country },
    },
    breadcrumbJsonLd(TRAIL),
  ];
  const faq = faqJsonLd(FAQ);
  if (faq) {
    structuredData.push(faq);
  }

  return (
    <main id="contenu">
      {/* ─── Header ──────────────────────────────────────────────────── */}
      <section
        aria-labelledby="trading-titre"
        className="relative overflow-hidden bg-navy-700 text-white"
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-20 -right-10 h-56 w-96 rotate-6 rounded-[100%] bg-gradient-to-r from-leaf/25 to-leaf-light/10 blur-2xl"
        />
        <Container className="relative py-12 sm:py-16">
          <div className="[&_a]:text-navy-100 [&_a:hover]:text-green-400 [&_span]:text-white">
            <Breadcrumbs trail={TRAIL} />
          </div>
          <p className="dally-signature mt-6 text-xs font-semibold text-green-400">
            Trading
          </p>
          <h1
            id="trading-titre"
            className="mt-3 max-w-3xl text-3xl font-bold leading-tight sm:text-4xl"
          >
            Proposez-nous votre opération commerciale
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-navy-100">
            Un lot à placer, un besoin à couvrir, une mise en relation à sécuriser ou
            une représentation à confier : décrivez l’opération, nous vous dirons
            comment la structurer.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <CtaLink href="#proposition">Proposer une opération</CtaLink>
            <CtaLink href="/contact" variant="onNavy">
              Parler à un conseiller
            </CtaLink>
          </div>
        </Container>
      </section>

      {/* ─── The six operation types ─────────────────────────────────── */}
      <Section labelledBy="types-titre" tone="white">
        <Container>
          <SectionHeading
            id="types-titre"
            eyebrow="Nos modes d’intervention"
            title="Six façons de travailler ensemble"
            lead="Elles n’engagent pas les mêmes responsabilités ni la même rémunération. Choisir la bonne dès le départ fait gagner un aller-retour."
          />
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {TRADE_OPERATION_TYPES.map((type) => (
              <article
                key={type.value}
                className="rounded-2xl border border-mist-200 bg-mist-50 p-6"
              >
                <h3 className="text-lg font-bold text-navy-800">{type.label}</h3>
                <span aria-hidden="true" className="dally-swoosh mt-3 block w-10" />
                <p className="mt-4 text-sm leading-relaxed text-mist-600">
                  {type.hint}
                </p>
              </article>
            ))}
          </div>
          <p className="mt-8 text-sm text-mist-600">
            Vous cherchez plutôt un fournisseur ou un produit précis ? C’est du{' '}
            <Link href="/sourcing" className="font-medium text-navy-700 underline">
              sourcing
            </Link>
            . Pour comprendre notre métier de négoce avant de proposer quoi que ce
            soit, voir{' '}
            <Link
              href="/activites/commerce-trading"
              className="font-medium text-navy-700 underline"
            >
              Commerce &amp; Trading
            </Link>
            .
          </p>
        </Container>
      </Section>

      {/* ─── What we do, and how it runs ─────────────────────────────── */}
      <Section labelledBy="deroule-titre" tone="mist">
        <Container>
          <div className="grid gap-12 lg:grid-cols-2 lg:items-start">
            <div>
              <SectionHeading
                id="deroule-titre"
                title="Ce que nous prenons en charge"
              />
              <p className="mt-6 leading-relaxed text-mist-700">
                Une opération commerciale n’est pas un transport : c’est une
                transaction, avec deux contreparties, des conditions à négocier et une
                exécution à sécuriser. Nous intervenons comme négociant ou comme
                intermédiaire, selon ce qui sert le mieux l’opération — et nous le
                disons explicitement dans la proposition.
              </p>
              <div className="mt-8">
                <CheckList
                  items={[
                    'Structuration de l’opération et choix du mode d’intervention',
                    'Identification et qualification des contreparties',
                    'Négociation des conditions commerciales',
                    'Coordination logistique et documentaire',
                    'Suivi de l’exécution jusqu’au règlement',
                    'Représentation commerciale au Sénégal',
                  ]}
                />
              </div>
            </div>

            <aside
              aria-labelledby="etapes-titre"
              className="h-fit rounded-2xl border border-mist-200 bg-white p-7"
            >
              <h2 id="etapes-titre" className="text-lg font-bold text-navy-800">
                Comment ça se passe
              </h2>
              <span aria-hidden="true" className="dally-swoosh mt-3 block w-12" />
              <ol className="mt-5 space-y-5">
                {STEPS.map((entry) => (
                  <li key={entry.step} className="flex gap-4">
                    <span aria-hidden="true" className="font-bold text-leaf">
                      {entry.step}
                    </span>
                    <span>
                      <span className="block font-semibold text-navy-700">
                        {entry.title}
                      </span>
                      <span className="mt-1 block text-sm leading-relaxed text-mist-600">
                        {entry.text}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
            </aside>
          </div>
        </Container>
      </Section>

      {/* ─── The form ───────────────────────────────────────────────── */}
      <Section id="proposition" labelledBy="proposition-titre" tone="white">
        <Container size="narrow">
          <SectionHeading
            id="proposition-titre"
            eyebrow="Votre opération"
            title="Proposer une opération"
            lead="Six étapes courtes. Nous ne demandons que ce dont nous avons besoin pour vous répondre utilement, et vous recevez une référence de suivi dès l’envoi."
          />
          <div className="mt-10">
            <TradeForm />
          </div>
        </Container>
      </Section>

      {/* ─── FAQ ────────────────────────────────────────────────────── */}
      <Section labelledBy="faq-titre" tone="mist">
        <Container size="narrow">
          <SectionHeading
            id="faq-titre"
            eyebrow="Questions fréquentes"
            title="Le trading, concrètement"
          />
          {/* <details> keeps the answers in the DOM, which is what makes the FAQPage
              markup legitimate rather than cloaking. */}
          <div className="mt-10 divide-y divide-mist-200 rounded-xl border border-mist-200 bg-white">
            {FAQ.map((entry) => (
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
                <p className="mt-4 leading-relaxed text-mist-600">{entry.answer}</p>
              </details>
            ))}
          </div>
        </Container>
      </Section>

      {/* ─── Closing CTA ────────────────────────────────────────────── */}
      <Section labelledBy="trading-cta" tone="navy">
        <Container>
          <h2 id="trading-cta" className="text-2xl font-bold sm:text-3xl">
            Une opération à structurer ?
          </h2>
          <p className="mt-4 max-w-2xl leading-relaxed text-navy-100">
            Décrivez-la : nous vous dirons franchement si elle relève de notre
            périmètre, et nous vous orienterons dans le cas contraire.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <CtaLink href="#proposition">Proposer une opération</CtaLink>
            <CtaLink href="/sourcing" variant="onNavy">Demande de sourcing</CtaLink>
            <CtaLink href="/contact" variant="onNavy">Nous contacter</CtaLink>
          </div>
        </Container>
      </Section>

      <JsonLd data={structuredData} />
    </main>
  );
}
