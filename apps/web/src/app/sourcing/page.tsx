import type { Metadata } from 'next';
import {
  Breadcrumbs,
  CheckList,
  Container,
  CtaLink,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import { SourcingForm } from '@/features/sourcing/SourcingForm';
import {
  breadcrumbJsonLd,
  faqJsonLd,
  pageMetadata,
  type JsonLdObject,
} from '@/lib/seo';
import { CONTACT, SITE_URL } from '@/config/site';
import { findActivity } from '@/config/activities';

const TRAIL = [
  { label: 'Accueil', href: '/' },
  { label: 'Nos activités', href: '/activites' },
  { label: 'Sourcing' },
];

export const metadata: Metadata = pageMetadata({
  title: 'Sourcing international — Recherche de fournisseurs et de produits',
  description:
    'DallyTrading recherche vos produits, fabricants, grossistes et fournisseurs à ' +
    'l’international, vérifie leur sérieux et négocie pour vous. Déposez votre ' +
    'demande de sourcing en quelques minutes.',
  path: '/sourcing',
  keywords: [
    'sourcing Sénégal',
    'sourcing international Dakar',
    'recherche fournisseur Sénégal',
    'recherche fabricant international',
    'approvisionnement international Sénégal',
    'trouver un fournisseur Dakar',
  ],
});

/**
 * The sourcing landing page and request form.
 *
 * A server component wrapping a client island: the copy, the FAQ and the structured
 * data cost no JavaScript, and only the form — which genuinely needs state — ships as
 * a client component.
 *
 * Nothing here claims a capability nobody confirmed: no supplier count, no covered
 * countries, no guaranteed lead time, no savings percentage (§55). What is stated is
 * what the service does.
 */
export const dynamic = 'force-dynamic';

/** The real questions prospects ask, answered honestly. */
const FAQ = [
  {
    question: 'Qu’est-ce que le sourcing international ?',
    answer:
      'Le sourcing consiste à identifier des fournisseurs ou des fabricants capables de produire ou de livrer ce dont vous avez besoin, à comparer leurs offres, à vérifier ce qu’ils annoncent et à négocier des conditions tenables. Trouver un fournisseur en ligne est facile ; trouver un fournisseur fiable ne l’est pas.',
  },
  {
    question: 'DallyTrading peut-il rechercher un fournisseur pour mon produit ?',
    answer:
      'Décrivez votre produit, votre quantité et votre ordre de grandeur de budget : nous vous dirons franchement si la recherche relève de notre périmètre, et nous vous orienterons dans le cas contraire.',
  },
  {
    question: 'Puis-je demander un produit sans connaître le fournisseur ?',
    answer:
      'Oui, c’est le cas le plus courant. Vous décrivez ce que vous cherchez, nous identifions les fournisseurs. Vous n’avez besoin de connaître ni le fabricant, ni la référence exacte.',
  },
  {
    question: 'Dans quels pays recherchez-vous les fournisseurs ?',
    answer:
      'Nous travaillons principalement sur les axes Europe, Asie et Moyen-Orient vers le Sénégal. Si vous avez une préférence de pays, indiquez-la ; sinon nous cherchons là où le produit se trouve. Si votre besoin sort de nos axes, nous vous le dirons plutôt que de vous faire attendre.',
  },
  {
    question: 'Comment les fournisseurs sont-ils sélectionnés ?',
    answer:
      'Nous comparons les offres reçues sur le prix rendu, le délai, la quantité minimale et ce que nous avons pu vérifier du fournisseur. Nous vous restituons ce que nous constatons, y compris ce qui nous paraît douteux. Nous ne prétendons pas éliminer tout risque : nous le documentons pour que vous décidiez en connaissance de cause.',
  },
  {
    question: 'Puis-je demander un échantillon ?',
    answer:
      'Oui, lorsque le fournisseur en propose. Le coût de l’échantillon et de son acheminement vous est indiqué avant tout engagement.',
  },
  {
    question: 'Comment obtenir un devis ?',
    answer:
      'Déposez votre demande sur cette page. Vous recevez immédiatement une référence de suivi, puis notre proposition chiffrée une fois la recherche aboutie.',
  },
];

export default function SourcingPage() {
  const activity = findActivity('sourcing-international');

  const structuredData: JsonLdObject[] = [
    {
      '@context': 'https://schema.org',
      '@type': 'Service',
      '@id': `${SITE_URL}/sourcing#service`,
      name: 'Sourcing international',
      description:
        'Recherche de produits, de fabricants, de grossistes et de fournisseurs à ' +
        'l’international, vérification et négociation.',
      serviceType: 'Sourcing international',
      url: `${SITE_URL}/sourcing`,
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
        aria-labelledby="sourcing-titre"
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
            Sourcing international
          </p>
          <h1
            id="sourcing-titre"
            className="mt-3 max-w-3xl text-3xl font-bold leading-tight sm:text-4xl"
          >
            Trouvez les bons produits et les bons fournisseurs
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-navy-100">
            DallyTrading accompagne les entreprises, commerçants et entrepreneurs dans
            la recherche de produits, fabricants, grossistes et fournisseurs à
            l’international.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <CtaLink href="#demande">Déposer une demande de sourcing</CtaLink>
            <CtaLink href="/contact" variant="onNavy">
              Parler à un conseiller
            </CtaLink>
          </div>
        </Container>
      </section>

      {/* ─── What the service is ─────────────────────────────────────── */}
      <Section labelledBy="prestation-titre" tone="white">
        <Container>
          <div className="grid gap-12 lg:grid-cols-2 lg:items-start">
            <div>
              <SectionHeading
                id="prestation-titre"
                title="Ce que nous faisons pour vous"
              />
              <p className="mt-6 leading-relaxed text-mist-700">
                Trouver un fournisseur en ligne est facile ; trouver un fournisseur
                fiable ne l’est pas. Le sourcing consiste à identifier des candidats
                crédibles, comparer leurs offres, vérifier ce qu’ils annoncent et
                négocier des conditions tenables — puis, si vous le souhaitez, à
                organiser l’acheminement.
              </p>
              <div className="mt-8">
                <CheckList
                  items={
                    activity
                      ? activity.includes
                      : [
                          'Recherche de fournisseurs selon votre cahier des charges',
                          'Recherche de produits et d’équivalences',
                          'Comparaison des offres et des conditions',
                          'Vérification préalable des fournisseurs',
                          'Négociation des prix et des délais',
                          'Organisation du transport une fois l’accord conclu',
                        ]
                  }
                />
              </div>
            </div>

            <aside
              aria-labelledby="etapes-titre"
              className="h-fit rounded-2xl border border-mist-200 bg-mist-50 p-7"
            >
              <h2 id="etapes-titre" className="text-lg font-bold text-navy-800">
                Comment ça se passe
              </h2>
              <span aria-hidden="true" className="dally-swoosh mt-3 block w-12" />
              <ol className="mt-5 space-y-5">
                {[
                  {
                    step: '01',
                    title: 'Votre demande',
                    text: 'Vous décrivez le produit, la quantité et votre budget. Quelques minutes suffisent.',
                  },
                  {
                    step: '02',
                    title: 'Notre recherche',
                    text: 'Nous identifions des fournisseurs, les contactons et sollicitons leurs offres.',
                  },
                  {
                    step: '03',
                    title: 'La comparaison',
                    text: 'Nous comparons prix rendu, délais, quantités minimales et fiabilité.',
                  },
                  {
                    step: '04',
                    title: 'Notre proposition',
                    text: 'Vous recevez une proposition chiffrée, avec les conditions et les délais estimés.',
                  },
                ].map((entry) => (
                  <li key={entry.step} className="flex gap-4">
                    <span
                      aria-hidden="true"
                      className="font-bold text-leaf"
                    >
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
      <Section id="demande" labelledBy="demande-titre" tone="mist">
        <Container size="narrow">
          <SectionHeading
            id="demande-titre"
            eyebrow="Votre demande"
            title="Déposer une demande de sourcing"
            lead="Nous ne demandons que ce dont nous avons besoin pour lancer la recherche. Vous recevez une référence de suivi dès l’envoi."
          />
          <div className="mt-10">
            <SourcingForm />
          </div>
        </Container>
      </Section>

      {/* ─── FAQ ────────────────────────────────────────────────────── */}
      <Section labelledBy="faq-titre" tone="white">
        <Container size="narrow">
          <SectionHeading
            id="faq-titre"
            eyebrow="Questions fréquentes"
            title="Le sourcing, concrètement"
          />
          {/* <details> keeps the answers in the DOM, which is what makes the FAQPage
              markup legitimate rather than cloaking. */}
          <div className="mt-10 divide-y divide-mist-200 rounded-xl border border-mist-200">
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
      <Section labelledBy="sourcing-cta" tone="navy">
        <Container>
          <h2 id="sourcing-cta" className="text-2xl font-bold sm:text-3xl">
            Un produit à trouver ?
          </h2>
          <p className="mt-4 max-w-2xl leading-relaxed text-navy-100">
            Décrivez-le : nous vous dirons franchement si la recherche relève de notre
            périmètre, et nous vous orienterons dans le cas contraire.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <CtaLink href="#demande">Déposer une demande</CtaLink>
            <CtaLink href="/devis" variant="onNavy">Demander un devis</CtaLink>
            <CtaLink href="/contact" variant="onNavy">Nous contacter</CtaLink>
          </div>
        </Container>
      </Section>

      <JsonLd data={structuredData} />
    </main>
  );
}
