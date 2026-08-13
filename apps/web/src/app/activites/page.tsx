import type { Metadata } from 'next';
import {
  Breadcrumbs,
  Card,
  Container,
  CtaRow,
  Section,
  SectionHeading,
} from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import { ACTIVITIES, activityHref } from '@/config/activities';
import { activityListJsonLd, breadcrumbJsonLd, pageMetadata } from '@/lib/seo';

const TRAIL = [
  { label: 'Accueil', href: '/' },
  { label: 'Nos activités' },
];

export const metadata: Metadata = pageMetadata({
  title: 'Nos activités — Import-export, fret, commerce et sourcing',
  description:
    'Les onze activités de DallyTrading : import-export, logistique, fret maritime ' +
    'et aérien, transport de véhicules, groupage, commerce, trading, sourcing, ' +
    'e-commerce, agrobusiness et solutions entreprises.',
  path: '/activites',
  keywords: [
    'activités DallyTrading',
    'import export Sénégal',
    'fret Sénégal',
    'logistique Dakar',
    'sourcing Sénégal',
  ],
});

/** Activity hub, grouped so eleven cards do not read as an undifferentiated list. */
const GROUPS = [
  {
    id: 'commerce',
    title: 'Commerce et approvisionnement',
    lead: 'Trouver, acheter, négocier, revendre.',
    slugs: [
      'import-export',
      'sourcing-international',
      'commerce-trading',
      'agrobusiness',
    ],
  },
  {
    id: 'transport',
    title: 'Transport et logistique',
    lead: 'Acheminer, stocker, distribuer, suivre.',
    slugs: [
      'fret-maritime',
      'fret-aerien',
      'transport-vehicules',
      'groupage',
      'logistique-transport',
    ],
  },
  {
    id: 'services',
    title: 'Services et solutions',
    lead: 'Vendre en ligne, s’implanter, se faire représenter.',
    slugs: ['e-commerce', 'solutions-entreprises'],
  },
] as const;

export default function ActivitiesPage() {
  return (
    <main id="contenu">
      <Section labelledBy="activites-titre" tone="white" className="pb-6">
        <Container>
          <Breadcrumbs trail={TRAIL} />
          <div className="mt-6">
            <SectionHeading
              id="activites-titre"
              eyebrow="Nos activités"
              title="Onze métiers, une seule entreprise"
              lead="DallyTrading est une entreprise multisectorielle. Nous intervenons sur le commerce et l’approvisionnement, le transport et la logistique, et l’accompagnement des entreprises."
            />
          </div>
          <CtaRow className="mt-8" />
        </Container>
      </Section>

      {GROUPS.map((group, index) => {
        const activities = group.slugs
          .map((slug) => ACTIVITIES.find((activity) => activity.slug === slug))
          .filter((activity): activity is (typeof ACTIVITIES)[number] =>
            activity !== undefined,
          );

        return (
          <Section
            key={group.id}
            id={group.id}
            labelledBy={`${group.id}-titre`}
            tone={index % 2 === 0 ? 'mist' : 'white'}
          >
            <Container>
              <SectionHeading
                id={`${group.id}-titre`}
                title={group.title}
                lead={group.lead}
              />
              <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
                {activities.map((activity) => (
                  <Card
                    key={activity.slug}
                    href={activityHref(activity)}
                    title={activity.title}
                    footer={
                      <span className="text-sm font-semibold text-green-700">
                        En savoir plus <span aria-hidden="true">→</span>
                      </span>
                    }
                  >
                    {activity.summary}
                  </Card>
                ))}
              </div>
            </Container>
          </Section>
        );
      })}

      <Section labelledBy="activites-cta" tone="navy">
        <Container>
          <h2 id="activites-cta" className="text-2xl font-bold sm:text-3xl">
            Votre besoin ne figure pas dans la liste ?
          </h2>
          <p className="mt-4 max-w-2xl leading-relaxed text-navy-100">
            Décrivez-le : nous vous dirons franchement s’il relève de notre périmètre,
            et vers qui vous orienter dans le cas contraire.
          </p>
          <CtaRow onDark className="mt-8" />
        </Container>
      </Section>

      <JsonLd data={[activityListJsonLd(), breadcrumbJsonLd(TRAIL)]} />
    </main>
  );
}
