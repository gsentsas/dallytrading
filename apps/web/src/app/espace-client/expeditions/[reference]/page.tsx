import Link from 'next/link';
import type { Metadata } from 'next';

import {
  Card, Detail, PageHeader, StatusBadge, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getShipment } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Détail de l’expédition' };
export const dynamic = 'force-dynamic';

/**
 * Détail d'une expédition — suivi compris, sans token.
 *
 * ## Deux chemins vers le même suivi, et ils restent séparés
 *
 * Le suivi public exige `référence + token` : c'est ce qui permet à un
 * destinataire non authentifié de suivre un colis depuis un lien. Ici, l'identité
 * de la session tient lieu de preuve, et le token n'est ni demandé, ni affiché,
 * ni même présent dans la projection.
 *
 * Ne pas l'exposer est délibéré : un token affiché sur cette page finirait copié
 * dans un e-mail, transmis, et deviendrait un accès permanent que personne ne
 * peut révoquer individuellement.
 *
 * La timeline est déjà filtrée sur `visible_to_customer` par la record rule. Le
 * frontend ne refiltre pas — refiltrer laisserait croire que c'est lui la barrière.
 */
export default async function ShipmentDetailPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const shipment = await loadPortal(() => getShipment(reference, newCorrelationId()));

  if (!shipment) {
    return (
      <>
        <PageHeader title="Expédition" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <Link
        href="/espace-client/expeditions"
        className="text-sm text-green-800 hover:underline"
      >
        ← Retour aux expéditions
      </Link>
      <div className="mt-4">
        <PageHeader title={shipment.reference} />
      </div>

      <Card className="mb-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <StatusBadge label={shipment.statusLabel} />
          <span className="text-sm text-mist-600">
            {shipment.transportModeLabel ?? '—'}
          </span>
        </div>
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Detail label="Origine" value={shipment.origin} />
          <Detail label="Destination" value={shipment.destination} />
          <Detail label="Départ" value={shipment.departureDate} />
          <Detail label="Arrivée estimée" value={shipment.estimatedArrival} />
          <Detail label="Arrivée réelle" value={shipment.actualArrival} />
          <Detail label="Dernière mise à jour" value={shipment.lastUpdate} />
          <Detail label="N° de suivi transporteur" value={shipment.carrierTrackingNumber} />
          <Detail label="N° de conteneur" value={shipment.containerNumber} />
          <Detail label="Nombre de colis" value={shipment.packagesCount} />
        </dl>
        {shipment.goodsDescription && (
          <div className="mt-6">
            <h2 className="text-sm text-mist-600">Marchandise</h2>
            <p className="mt-1 whitespace-pre-line text-navy-800">
              {shipment.goodsDescription}
            </p>
          </div>
        )}
      </Card>

      <section aria-labelledby="colis" className="mb-6">
        <h2 id="colis" className="mb-4 text-lg font-semibold text-navy-800">Colis</h2>
        {shipment.packages.length === 0 ? (
          <Card><p className="text-mist-600">Aucun colis détaillé.</p></Card>
        ) : (
          <TableWrapper>
            <table className="w-full min-w-[36rem] border-collapse bg-white text-left">
              <caption className="sr-only">Colis de cette expédition</caption>
              <thead>
                <tr className="border-b border-mist-300 text-sm text-mist-600">
                  <th scope="col" className="p-3">Type</th>
                  <th scope="col" className="p-3">Description</th>
                  <th scope="col" className="p-3">Quantité</th>
                  <th scope="col" className="p-3">Poids (kg)</th>
                  <th scope="col" className="p-3">Volume (m³)</th>
                </tr>
              </thead>
              <tbody>
                {shipment.packages.map((pack, index) => (
                  <tr key={index} className="border-b border-mist-200">
                    <td className="p-3 text-navy-800">{pack.packageType ?? '—'}</td>
                    <td className="p-3 text-navy-800">{pack.description ?? '—'}</td>
                    <td className="p-3 text-navy-800">{pack.quantity}</td>
                    <td className="p-3 text-navy-800">{pack.totalWeightKg}</td>
                    <td className="p-3 text-navy-800">{pack.totalVolumeCbm}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrapper>
        )}
      </section>

      <section aria-labelledby="suivi">
        <h2 id="suivi" className="mb-4 text-lg font-semibold text-navy-800">Suivi</h2>
        {shipment.timeline.length === 0 ? (
          <Card><p className="text-mist-600">Aucun événement publié pour le moment.</p></Card>
        ) : (
          <Card>
            <ol className="space-y-4">
              {shipment.timeline.map((event, index) => (
                <li key={index} className="border-l-2 border-green-700 pl-4">
                  <p className="font-medium text-navy-800">{event.statusLabel}</p>
                  <p className="text-sm text-mist-600">
                    {event.date ?? '—'}
                    {event.location ? ` — ${event.location}` : ''}
                  </p>
                  {event.description && (
                    <p className="mt-1 text-navy-800">{event.description}</p>
                  )}
                </li>
              ))}
            </ol>
          </Card>
        )}
      </section>
    </>
  );
}
