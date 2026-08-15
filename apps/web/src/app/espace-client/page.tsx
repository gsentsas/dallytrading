import Link from 'next/link';

import { Card, PageHeader, StatusBadge, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getDashboard } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

/**
 * Tableau de bord.
 *
 * Un seul appel, `/api/v1/portal/dashboard`, qui renvoie déjà les compteurs et
 * les cinq derniers dossiers de chaque type. Reconstituer la même chose depuis
 * Next demanderait dix appels — cinq comptages et cinq listes — pour un résultat
 * identique, plus lent, et qui divergerait le jour où Odoo changerait sa
 * définition de « récent ».
 *
 * Aucun chiffre n'est calculé ici. Tout ce qui est affiché vient de la projection.
 */
export const dynamic = 'force-dynamic';

const SECTIONS = [
  { key: 'quotes', label: 'Devis', href: '/espace-client/devis' },
  { key: 'sourcing', label: 'Sourcing', href: '/espace-client/sourcing' },
  { key: 'trades', label: 'Trading', href: '/espace-client/trading' },
  { key: 'shipments', label: 'Expéditions', href: '/espace-client/expeditions' },
  { key: 'documents', label: 'Documents', href: '/espace-client/documents' },
] as const;

export default async function DashboardPage() {
  const dashboard = await loadPortal(() => getDashboard(newCorrelationId()));

  if (!dashboard) {
    return (
      <>
        <PageHeader title="Tableau de bord" />
        <UnavailableState />
      </>
    );
  }

  const { counters, recent } = dashboard;

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        description="Vue d’ensemble de vos dossiers en cours."
      />

      <section aria-labelledby="compteurs" className="mb-8">
        <h2 id="compteurs" className="sr-only">
          Compteurs par section
        </h2>
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {SECTIONS.map((section) => (
            <li key={section.key}>
              <Link
                href={section.href}
                className="block rounded-xl border border-mist-300 bg-white p-4 transition-colors hover:border-green-700"
              >
                <span className="block text-3xl font-bold text-navy-900">
                  {counters[section.key]}
                </span>
                <span className="mt-1 block text-sm text-mist-600">
                  {section.label}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="text-lg font-semibold text-navy-800">Expéditions récentes</h2>
          {recent.shipments.length === 0 ? (
            <p className="mt-4 text-mist-600">Aucune expédition en cours.</p>
          ) : (
            <ul className="mt-4 divide-y divide-mist-200">
              {recent.shipments.map((shipment) => (
                <li key={shipment.reference} className="py-3">
                  <Link
                    href={`/espace-client/expeditions/${encodeURIComponent(shipment.reference)}`}
                    className="flex flex-wrap items-center justify-between gap-2 hover:underline"
                  >
                    <span className="font-medium text-navy-800">
                      {shipment.reference}
                    </span>
                    <StatusBadge label={shipment.statusLabel} />
                  </Link>
                  <p className="mt-1 text-sm text-mist-600">
                    {shipment.origin ?? '—'} → {shipment.destination ?? '—'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="text-lg font-semibold text-navy-800">Devis récents</h2>
          {recent.quotes.length === 0 ? (
            <p className="mt-4 text-mist-600">Aucune demande de devis.</p>
          ) : (
            <ul className="mt-4 divide-y divide-mist-200">
              {recent.quotes.map((quote) => (
                <li key={quote.reference} className="py-3">
                  <Link
                    href={`/espace-client/devis/${encodeURIComponent(quote.reference)}`}
                    className="flex flex-wrap items-center justify-between gap-2 hover:underline"
                  >
                    <span className="font-medium text-navy-800">{quote.reference}</span>
                    <StatusBadge label={quote.status} />
                  </Link>
                  <p className="mt-1 text-sm text-mist-600">
                    {quote.createdOn ?? '—'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="text-lg font-semibold text-navy-800">Sourcing récent</h2>
          {recent.sourcing.length === 0 ? (
            <p className="mt-4 text-mist-600">Aucune demande de sourcing.</p>
          ) : (
            <ul className="mt-4 divide-y divide-mist-200">
              {recent.sourcing.map((request) => (
                <li key={request.reference} className="py-3">
                  <Link
                    href={`/espace-client/sourcing/${encodeURIComponent(request.reference)}`}
                    className="flex flex-wrap items-center justify-between gap-2 hover:underline"
                  >
                    <span className="font-medium text-navy-800">
                      {request.reference}
                    </span>
                    <StatusBadge label={request.status} />
                  </Link>
                  <p className="mt-1 text-sm text-mist-600">
                    {request.productName ?? '—'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="text-lg font-semibold text-navy-800">Opérations récentes</h2>
          {recent.trades.length === 0 ? (
            <p className="mt-4 text-mist-600">Aucune opération commerciale.</p>
          ) : (
            <ul className="mt-4 divide-y divide-mist-200">
              {recent.trades.map((trade) => (
                <li key={trade.reference} className="py-3">
                  <Link
                    href={`/espace-client/trading/${encodeURIComponent(trade.reference)}`}
                    className="flex flex-wrap items-center justify-between gap-2 hover:underline"
                  >
                    <span className="font-medium text-navy-800">{trade.reference}</span>
                    <StatusBadge label={trade.status} />
                  </Link>
                  <p className="mt-1 text-sm text-mist-600">{trade.subject}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
