import type { Metadata } from 'next';
import { QuoteForm } from '@/features/quote/QuoteForm';
import { getServiceCatalogue } from '@/services/odoo/catalogue-cache';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = {
  title: 'Demander un devis',
  description:
    'Demandez un devis pour vos opérations d’import-export, de fret maritime ou ' +
    'aérien, de transport de véhicules, de groupage, de sourcing ou de trading. ' +
    'Réponse rapide de nos équipes à Dakar.',
  alternates: { canonical: '/devis' },
};

/**
 * Rendered on demand, because the catalogue comes from Odoo.
 *
 * The page could be cached, but the catalogue cache already absorbs the load: a
 * page-level cache on top would add a second, independent staleness window and
 * make "why is the old service still showing" impossible to reason about.
 */
export const dynamic = 'force-dynamic';

export default async function QuotePage() {
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
    // nothing: showing a service list invented in the front end would be the
    // second business list this design exists to remove, and it would offer
    // services that may have been withdrawn.
    unavailable = true;
  }

  return (
    <main id="contenu" className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-bold text-navy-800 sm:text-4xl">
        Demander un devis
      </h1>
      <p className="mt-4 text-mist-600">
        Quelques questions suffisent. Nous ne demandons que ce qui concerne le
        service choisi, et vous recevez une référence de suivi dès l’envoi.
      </p>

      {unavailable ? (
        <div
          className="mt-10 rounded-xl border border-mist-300 bg-mist-100 p-6"
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
            Votre demande est urgente ? Écrivez-nous directement par e-mail ou sur
            WhatsApp : nos équipes vous répondront sans passer par ce formulaire.
          </p>
        </div>
      ) : (
        <div className="mt-10">
          <QuoteForm services={services} catalogueStale={stale} />
        </div>
      )}

      <p className="mt-10 text-sm text-mist-600">
        Vous préférez échanger de vive voix ? Écrivez-nous sur WhatsApp ou par
        e-mail depuis la page contact.
      </p>
    </main>
  );
}
