import type { Metadata } from 'next';
import { Breadcrumbs, Container, CtaLink } from '@/components/ui/primitives';
import { JsonLd } from '@/components/seo/JsonLd';
import { QuoteForm } from '@/features/quote/QuoteForm';
import { getServiceCatalogue } from '@/services/odoo/catalogue-cache';
import { getPublicReferences } from '@/services/odoo/references-cache';
import { newCorrelationId } from '@/lib/logger';
import { breadcrumbJsonLd, pageMetadata } from '@/lib/seo';

const TRAIL = [{ label: 'Accueil', href: '/' }, { label: 'Demander un devis' }];

export const metadata: Metadata = pageMetadata({
  title: 'Demander un devis',
  description:
    'Demandez un devis pour vos opérations d’import-export, de fret maritime ou ' +
    'aérien, de transport de véhicules, de groupage, de sourcing ou de trading. ' +
    'Réponse rapide de nos équipes à Dakar.',
  path: '/devis',
  keywords: [
    'devis fret Sénégal',
    'devis import export Dakar',
    'devis transport Sénégal',
    'tarif fret maritime Sénégal',
  ],
});

/**
 * Rendered on demand, because the catalogue comes from Odoo.
 *
 * The page is not additionally cached: the catalogue cache already absorbs the load,
 * and a second independent staleness window would make "why is the old service still
 * showing" impossible to reason about.
 */
export const dynamic = 'force-dynamic';

export default async function QuotePage({
  searchParams,
}: {
  searchParams: Promise<{ service?: string }>;
}) {
  const { service: requestedService } = await searchParams;
  const correlationId = newCorrelationId();

  let services: Awaited<ReturnType<typeof getServiceCatalogue>>['services'] = [];
  let stale = false;
  let unavailable = false;

  try {
    const catalogue = await getServiceCatalogue(correlationId);
    services = catalogue.services;
    stale = catalogue.stale;
  } catch {
    // Odoo is unreachable and no copy is held. The form cannot be built from
    // nothing: a service list invented in the front end would be the second business
    // list this design exists to remove, and it would offer withdrawn services.
    unavailable = true;
  }

  // Les référentiels ne conditionnent pas l'ouverture du formulaire : sans eux,
  // les pays et les lieux ne sont pas proposés, mais les villes restent
  // saisissables à la main. `getPublicReferences` ne lève donc jamais et rend
  // des listes vides en dernier recours.
  const references = await getPublicReferences(correlationId);

  return (
    <main id="contenu">
      <Container className="py-12 sm:py-16" size="narrow">
        <Breadcrumbs trail={TRAIL} />

        <h1 className="mt-6 text-3xl font-bold text-navy-800 sm:text-4xl">
          Demander un devis
        </h1>
        <span aria-hidden="true" className="dally-swoosh mt-4 block w-16" />
        <p className="mt-5 leading-relaxed text-mist-600">
          Quelques questions suffisent. Nous ne demandons que ce qui concerne le
          service choisi, et vous recevez une référence de suivi dès l’envoi.
        </p>

        {unavailable ? (
          <div
            className="mt-10 rounded-xl border border-mist-300 bg-mist-50 p-6"
            role="alert"
          >
            <h2 className="text-lg font-bold text-navy-800">
              Formulaire momentanément indisponible
            </h2>
            <p className="mt-3 text-navy-800">
              Nous ne parvenons pas à charger notre catalogue de services. Merci de
              réessayer dans quelques minutes.
            </p>
            <p className="mt-4 text-navy-800">
              Votre demande est urgente ? Écrivez-nous directement : nos équipes vous
              répondront sans passer par ce formulaire.
            </p>
            <CtaLink href="/contact" className="mt-5">
              Nous contacter
            </CtaLink>
          </div>
        ) : (
          <div className="mt-10">
            <QuoteForm
              services={services}
              catalogueStale={stale}
              countries={references.countries}
              locations={references.locations}
              incoterms={references.incoterms}
              {...(requestedService ? { initialServiceCode: requestedService } : {})}
            />
          </div>
        )}

        <p className="mt-10 text-sm text-mist-600">
          Vous préférez échanger de vive voix ? Écrivez-nous sur WhatsApp, ou depuis
          la{' '}
          <a href="/contact" className="font-semibold text-green-700 hover:underline">
            page contact
          </a>
          .
        </p>
      </Container>

      <JsonLd data={breadcrumbJsonLd(TRAIL)} />
    </main>
  );
}
