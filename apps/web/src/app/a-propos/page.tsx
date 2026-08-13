import type { Metadata } from 'next';
import {
  Breadcrumbs,
  CheckList,
  Container,
  CtaRow,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import { Logo } from '@/components/brand/Logo';
import { ACTIVITIES } from '@/config/activities';
import { CONTACT, PARTNER_SEN_CONTAINERS } from '@/config/site';
import { breadcrumbJsonLd, pageMetadata } from '@/lib/seo';

const TRAIL = [{ label: 'Accueil', href: '/' }, { label: 'À propos' }];

export const metadata: Metadata = pageMetadata({
  title: 'À propos de DallyTrading',
  description:
    'DallyTrading est une entreprise multisectorielle basée au Sénégal : ' +
    'import-export, commerce, trading, sourcing, logistique et fret. Un seul ' +
    'interlocuteur pour vos opérations commerciales et internationales.',
  path: '/a-propos',
  keywords: [
    'DallyTrading',
    'Dally Trading',
    'entreprise import export Dakar',
    'société logistique Sénégal',
  ],
});

/**
 * About page.
 *
 * Deliberately free of figures: no founding year, no headcount, no client count, no
 * tonnage, no certifications. None of that was supplied, and inventing a credential
 * on a company's own site is not a copywriting shortcut — it is a false statement
 * its salespeople then have to defend in front of a customer.
 *
 * What is here instead is what can be stated truthfully: the scope of the business,
 * how it works, and where it operates.
 */
export default function AboutPage() {
  return (
    <main id="contenu">
      <section
        aria-labelledby="apropos-titre"
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
            À propos
          </p>
          <h1
            id="apropos-titre"
            className="mt-3 max-w-3xl text-3xl font-bold leading-tight sm:text-4xl"
          >
            Une entreprise multisectorielle, basée au Sénégal
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-navy-100">
            DallyTrading intervient sur le commerce, l’import-export, la logistique et
            l’accompagnement des entreprises. Nos métiers se combinent, et c’est
            précisément ce qui nous permet de suivre un dossier de bout en bout.
          </p>
        </Container>
      </section>

      {/* ─── Who we are ─────────────────────────────────────────────── */}
      <Section labelledBy="identite-titre" tone="white">
        <Container>
          <div className="grid gap-12 lg:grid-cols-2 lg:items-start">
            <div>
              <SectionHeading
                id="identite-titre"
                eyebrow="Notre positionnement"
                title="Le commerce et la logistique, ensemble"
              />
              <div className="mt-6 space-y-5 leading-relaxed text-mist-700">
                <p>
                  La plupart des opérations que l’on nous confie ne sont ni du transport
                  pur ni du commerce pur. Faire venir une marchandise suppose de trouver
                  un fournisseur, de négocier, d’organiser un acheminement, de préparer
                  des documents et d’assurer une livraison. Découper cette chaîne entre
                  plusieurs prestataires crée autant de zones où personne n’est
                  responsable.
                </p>
                <p>
                  DallyTrading a été construite pour couvrir cette chaîne. Nous sommes
                  négociants, commissionnaires, sourceurs et logisticiens, et nous
                  restons votre interlocuteur du premier échange jusqu’à la livraison.
                </p>
                <p>
                  Nous travaillons avec des particuliers qui font venir un achat ponctuel,
                  des commerçants qui approvisionnent leur stock, et des entreprises qui
                  ont des flux réguliers ou cherchent un relais au Sénégal.
                </p>
              </div>
            </div>

            <div className="rounded-2xl border border-mist-200 bg-mist-50 p-7">
              <h2 className="text-lg font-bold text-navy-800">Nos métiers</h2>
              <span aria-hidden="true" className="dally-swoosh mt-3 block w-12" />
              <div className="mt-5">
                <CheckList items={ACTIVITIES.map((activity) => activity.title)} />
              </div>
            </div>
          </div>
        </Container>
      </Section>

      {/* ─── How we work ────────────────────────────────────────────── */}
      <Section labelledBy="methode-titre" tone="mist">
        <Container>
          <SectionHeading
            id="methode-titre"
            eyebrow="Notre manière de travailler"
            title="Ce que vous pouvez attendre de nous"
            lead="Quatre engagements simples, qui décrivent notre pratique plutôt qu’une promesse commerciale."
          />
          <div className="mt-12 grid gap-6 sm:grid-cols-2">
            {[
              {
                title: 'Nous ne demandons que l’utile',
                text: 'Un formulaire de devis n’affiche que les questions pertinentes pour le service choisi. Vous ne remplissez pas un poids pour une recherche de fournisseur.',
              },
              {
                title: 'Nous chiffrons en expliquant',
                text: 'Un devis de fret indique son mode de calcul, y compris quand le poids taxable dépasse le poids réel. Vous savez sur quoi vous payez.',
              },
              {
                title: 'Nous documentons le suivi',
                text: 'Chaque expédition reçoit une référence et un lien de suivi personnel. Vous consultez son avancement sans avoir à téléphoner.',
              },
              {
                title: 'Nous disons non quand il faut',
                text: 'Une opération irréalisable, un délai intenable ou un besoin hors de notre périmètre : nous le disons d’emblée plutôt que de vous faire perdre du temps.',
              },
            ].map((entry) => (
              <div
                key={entry.title}
                className="rounded-xl border-l-4 border-leaf bg-white p-6"
              >
                <h3 className="font-semibold text-navy-700">{entry.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-mist-600">
                  {entry.text}
                </p>
              </div>
            ))}
          </div>
        </Container>
      </Section>

      {/* ─── Where ──────────────────────────────────────────────────── */}
      <Section labelledBy="zone-titre" tone="white">
        <Container>
          <div className="grid gap-10 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <SectionHeading
                id="zone-titre"
                eyebrow="Notre zone d’intervention"
                title={`Basés à ${CONTACT.city}, tournés vers l’international`}
              />
              <div className="mt-6 space-y-5 leading-relaxed text-mist-700">
                <p>
                  Notre base est au {CONTACT.country}, à {CONTACT.city}. C’est de là que
                  nous coordonnons les opérations, que nous suivons les arrivées et que
                  nous organisons la distribution locale.
                </p>
                <p>
                  Nos flux principaux relient l’Europe, l’Asie et le Moyen-Orient au
                  Sénégal, dans les deux sens, ainsi que la sous-région. Si votre axe
                  n’est pas couvert, nous vous le dirons plutôt que de vous laisser
                  attendre une réponse.
                </p>
              </div>
            </div>

            {/*
              SEN CONTAINERS: a commercial partnership. Stated factually and kept
              secondary to the DallyTrading brand (§35). Content only — no model, no
              API and no CRM connection anywhere in the system.
            */}
            <aside
              aria-labelledby="partenaire-apropos"
              className="h-fit rounded-2xl border border-mist-200 bg-mist-50 p-7"
            >
              <p className="dally-signature text-xs font-semibold text-green-700">
                Partenaire commercial
              </p>
              <h2
                id="partenaire-apropos"
                className="mt-3 text-lg font-bold text-navy-800"
              >
                {PARTNER_SEN_CONTAINERS.name}
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-mist-600">
                {PARTNER_SEN_CONTAINERS.summary}
              </p>
              <p className="mt-4 text-sm text-mist-500">
                DallyTrading intervient par ailleurs pour son propre compte sur
                l’ensemble de ses activités.
              </p>
            </aside>
          </div>
        </Container>
      </Section>

      {/* ─── Closing CTA ────────────────────────────────────────────── */}
      <Section labelledBy="apropos-cta" tone="navy">
        <Container>
          <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
            <div className="max-w-2xl">
              <h2
                id="apropos-cta"
                className="text-2xl font-bold text-white sm:text-3xl"
              >
                Travaillons ensemble
              </h2>
              <p className="mt-4 leading-relaxed text-navy-100">
                Une demande de devis prend quelques minutes. Vous préférez d’abord
                échanger ? Écrivez-nous, nous vous rappelons.
              </p>
              <div className="mt-8">
                <Logo size="sm" onDark showSignature={false} />
              </div>
            </div>
            <CtaRow onDark className="lg:shrink-0 lg:flex-col" />
          </div>
        </Container>
      </Section>

      <JsonLd data={breadcrumbJsonLd(TRAIL)} />
    </main>
  );
}
