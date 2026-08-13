import Link from 'next/link';
import type { Metadata } from 'next';
import {
  Card,
  Container,
  CtaLink,
  CtaRow,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { Logo } from '@/components/brand/Logo';
import { ACTIVITIES, activityHref, featuredActivities } from '@/config/activities';
import { PARTNER_SEN_CONTAINERS } from '@/config/site';
import { pageMetadata } from '@/lib/seo';

export const metadata: Metadata = pageMetadata({
  title: 'DallyTrading — Import-Export, Logistique et Fret au Sénégal',
  description:
    'DallyTrading accompagne particuliers, commerçants et entreprises dans leurs ' +
    'opérations commerciales, logistiques et internationales : import-export, fret ' +
    'maritime et aérien, transport de véhicules, groupage, sourcing, trading et ' +
    'agrobusiness.',
  path: '/',
  keywords: [
    'import export Sénégal',
    'import export Dakar',
    'logistique Sénégal',
    'transport Dakar',
    'fret maritime Sénégal',
    'fret aérien Sénégal',
    'groupage Sénégal',
    'sourcing Sénégal',
    'trading Sénégal',
    'commerce international Sénégal',
    'DallyTrading',
    'Dally Trading',
  ],
});

/**
 * Homepage.
 *
 * A server component throughout: no interactive state, so no client bundle beyond
 * the header and the WhatsApp button. That is what keeps the first paint fast on
 * the mobile connections this audience uses (§52).
 *
 * The structure follows §32–§35: hero, activities, how it works, why DallyTrading,
 * the SEN CONTAINERS partnership as a secondary mention, and a closing CTA.
 */
export default function HomePage() {
  return (
    <main id="contenu">
      {/* ─── Hero (§32) ──────────────────────────────────────────────── */}
      <section
        aria-labelledby="hero-titre"
        className="relative overflow-hidden bg-navy-700 text-white"
      >
        {/* Decorative leaf curve, echoing the logo's swoosh. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-24 -right-16 h-72 w-[36rem] rotate-6 rounded-[100%] bg-gradient-to-r from-leaf/25 to-leaf-light/10 blur-2xl"
        />
        <Container className="relative py-16 sm:py-24">
          <p className="dally-signature text-xs font-semibold text-green-400 sm:text-sm">
            Import • Export • Logistics • Solutions
          </p>
          <h1
            id="hero-titre"
            className="mt-5 max-w-3xl text-3xl font-bold leading-tight sm:text-4xl lg:text-5xl"
          >
            Votre partenaire pour le commerce, l’import-export et la logistique
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-navy-100">
            DallyTrading accompagne particuliers, commerçants et entreprises dans
            leurs opérations commerciales, logistiques et internationales. Un seul
            interlocuteur, du fournisseur jusqu’à la livraison.
          </p>

          <CtaRow onDark className="mt-10" />

          {/* Sectors covered, stated up front: the brief is explicit that the site
              must read as multisectoral, not as a freight forwarder alone. */}
          <ul className="mt-12 flex flex-wrap gap-2">
            {ACTIVITIES.map((activity) => (
              <li key={activity.slug}>
                <Link
                  href={activityHref(activity)}
                  className="inline-block rounded-full border border-navy-400 px-3 py-1.5 text-xs font-medium text-navy-100 transition-colors hover:border-green-400 hover:text-white"
                >
                  {activity.label}
                </Link>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* ─── Activities (§33) ────────────────────────────────────────── */}
      <Section labelledBy="activites-titre" tone="white">
        <Container>
          <SectionHeading
            id="activites-titre"
            eyebrow="Nos activités"
            title="Une entreprise multisectorielle"
            lead="Du sourcing à la livraison, du négoce à la représentation commerciale : nous couvrons l’ensemble de la chaîne entre le Sénégal et l’international."
          />

          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {featuredActivities().map((activity) => (
              <Card
                key={activity.slug}
                href={activityHref(activity)}
                title={activity.title}
                footer={
                  <span className="text-sm font-semibold text-green-700">
                    En savoir plus{' '}
                    <span aria-hidden="true">→</span>
                  </span>
                }
              >
                {activity.summary}
              </Card>
            ))}
          </div>

          <div className="mt-10">
            <CtaLink href="/activites" variant="ghost">
              Voir les onze activités
            </CtaLink>
          </div>
        </Container>
      </Section>

      {/* ─── How it works ───────────────────────────────────────────── */}
      <Section labelledBy="demarche-titre" tone="mist">
        <Container>
          <SectionHeading
            id="demarche-titre"
            eyebrow="Notre démarche"
            title="Comment nous travaillons"
            lead="Une demande claire, une réponse chiffrée, un suivi documenté. Vous savez à chaque étape où en est votre dossier."
          />

          <ol className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                step: '01',
                title: 'Votre demande',
                text: 'Vous décrivez votre besoin en quelques minutes. Nous ne posons que les questions utiles au service choisi.',
              },
              {
                step: '02',
                title: 'Notre étude',
                text: 'Nous analysons la faisabilité, comparons les options et vous indiquons franchement ce qui est réalisable.',
              },
              {
                step: '03',
                title: 'Votre devis',
                text: 'Vous recevez une proposition détaillée, avec le mode de calcul et les délais estimés.',
              },
              {
                step: '04',
                title: 'Le suivi',
                text: 'Une référence de suivi vous est attribuée. Vous consultez l’avancement de votre expédition à tout moment.',
              },
            ].map((entry) => (
              <li
                key={entry.step}
                className="rounded-xl border border-mist-200 bg-white p-6"
              >
                <p
                  aria-hidden="true"
                  className="text-2xl font-bold text-leaf"
                >
                  {entry.step}
                </p>
                <h3 className="mt-3 font-semibold text-navy-700">{entry.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-mist-600">
                  {entry.text}
                </p>
              </li>
            ))}
          </ol>
        </Container>
      </Section>

      {/* ─── Why DallyTrading ───────────────────────────────────────── */}
      <Section labelledBy="atouts-titre" tone="white">
        <Container>
          <div className="grid gap-12 lg:grid-cols-2 lg:items-start">
            <div>
              <SectionHeading
                id="atouts-titre"
                eyebrow="Pourquoi DallyTrading"
                title="Un interlocuteur unique, du début à la fin"
                lead="Multiplier les prestataires multiplie les zones d’ombre. Nous coordonnons l’ensemble et restons responsables du dossier."
              />
              <div className="mt-8">
                <CtaLink href="/a-propos" variant="ghost">
                  En savoir plus sur nous
                </CtaLink>
              </div>
            </div>

            <ul className="grid gap-6 sm:grid-cols-2">
              {[
                {
                  title: 'Plusieurs métiers, un seul dossier',
                  text: 'Commerce, fret, sourcing et représentation : vous ne changez pas d’interlocuteur en cours de route.',
                },
                {
                  title: 'Tous les modes de transport',
                  text: 'Maritime, aérien, routier, véhicules et groupage. Nous choisissons selon votre délai et votre budget.',
                },
                {
                  title: 'Un suivi consultable',
                  text: 'Chaque expédition a sa référence et son lien de suivi. Vous n’avez pas à téléphoner pour savoir où elle est.',
                },
                {
                  title: 'Des réponses honnêtes',
                  text: 'Si une opération n’est pas réalisable ou sort de notre périmètre, nous le disons plutôt que de vous faire attendre.',
                },
              ].map((entry) => (
                <li
                  key={entry.title}
                  className="rounded-xl border-l-4 border-leaf bg-mist-50 p-5"
                >
                  <h3 className="font-semibold text-navy-700">{entry.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-mist-600">
                    {entry.text}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </Container>
      </Section>

      {/* ─── SEN CONTAINERS (§35) ───────────────────────────────────── */}
      {/*
        Stated once, kept clearly secondary to the DallyTrading brand. Content only:
        no model, no API, no CRM connection anywhere in the system.
      */}
      <Section labelledBy="partenaire-titre" tone="mist">
        <Container size="narrow">
          <div className="rounded-2xl border border-mist-200 bg-white p-8">
            <p className="dally-signature text-xs font-semibold text-green-700">
              Partenaire commercial
            </p>
            <h2
              id="partenaire-titre"
              className="mt-3 text-xl font-bold text-navy-800 sm:text-2xl"
            >
              Représentant de {PARTNER_SEN_CONTAINERS.name} au Sénégal
            </h2>
            <p className="mt-4 leading-relaxed text-mist-600">
              {PARTNER_SEN_CONTAINERS.summary}
            </p>
            <p className="mt-4 text-sm text-mist-500">
              Cette représentation s’ajoute à nos activités propres : DallyTrading
              intervient pour son propre compte sur l’ensemble des métiers présentés
              sur ce site.
            </p>
          </div>
        </Container>
      </Section>

      {/* ─── Closing CTA ────────────────────────────────────────────── */}
      <Section labelledBy="cta-titre" tone="navy">
        <Container>
          <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
            <div className="max-w-2xl">
              <h2
                id="cta-titre"
                className="text-2xl font-bold text-white sm:text-3xl"
              >
                Parlons de votre projet
              </h2>
              <p className="mt-4 leading-relaxed text-navy-100">
                Décrivez votre besoin en quelques minutes et recevez une référence de
                suivi immédiatement. Vous préférez échanger de vive voix ? Écrivez-nous
                sur WhatsApp.
              </p>
              <div className="mt-8">
                <Logo size="sm" onDark showSignature={false} />
              </div>
            </div>
            <CtaRow onDark className="lg:shrink-0 lg:flex-col" />
          </div>
        </Container>
      </Section>
    </main>
  );
}
