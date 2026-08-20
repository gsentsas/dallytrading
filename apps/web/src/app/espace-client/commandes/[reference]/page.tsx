import Link from 'next/link';
import type { Metadata } from 'next';

import { Card, Detail, PageHeader, StatusBadge, TableWrapper, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { formatOrderAmount, formatOrderDate, formatQuantity } from '@/features/shop/order-format';
import { getShopOrder } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Commande' };
export const dynamic = 'force-dynamic';

export default async function CommandePage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const commande = await loadPortal(() =>
    getShopOrder(decodeURIComponent(reference), newCorrelationId()),
  );

  if (!commande) {
    return (
      <>
        <PageHeader title="Commande" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader title={`Commande ${commande.reference}`} />

      <Link
        href="/espace-client/commandes"
        className="mb-6 inline-flex text-sm text-navy-800 underline"
      >
        Retour à mes commandes
      </Link>

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <dl className="grid flex-1 gap-4 sm:grid-cols-2">
            <Detail label="Commande" value={commande.reference} />
            <Detail label="Date" value={formatOrderDate(commande.date)} />
            <Detail label="Mode de remise" value={commande.deliveryModeLabel || '—'} />
          </dl>
          <StatusBadge label={commande.stateLabel} />
        </div>

        {commande.state === 'received' && (
          <p className="mt-6 rounded-lg border border-mist-200 bg-mist-50 p-4 text-sm text-mist-700">
            Nous avons bien reçu cette commande. Nos équipes vérifient la
            disponibilité et vous recontactent pour la valider, ainsi que pour le
            coût de la remise et les modalités de règlement. Aucun paiement n’a
            été demandé.
          </p>
        )}
        {commande.state === 'validated' && (
          <p className="mt-6 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-900">
            Votre commande a été validée par nos équipes. Les prochaines étapes de
            remise, de paiement et de préparation vous seront communiquées selon
            les modalités convenues.
          </p>
        )}
        {commande.state === 'rejected' && (
          <p className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            Cette commande ne peut pas être validée dans son état actuel. Le motif
            communiqué par nos équipes figure dans le statut ci-dessus.
          </p>
        )}
        {commande.state === 'cancelled' && (
          <p className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            Cette commande a été annulée. Le motif communiqué par nos équipes
            figure dans le statut ci-dessus. Contactez-nous si vous avez besoin
            d’aide.
          </p>
        )}
      </Card>

      <h2 className="mt-8 text-lg font-semibold text-navy-900">Articles</h2>
      <TableWrapper>
        <table className="mt-3 w-full min-w-[36rem] border-collapse bg-white text-left">
          <caption className="sr-only">
            Articles de la commande {commande.reference}
          </caption>
          <thead>
            <tr className="border-b border-mist-300 text-sm text-mist-600">
              <th scope="col" className="p-3">Article</th>
              <th scope="col" className="p-3">Quantité</th>
              <th scope="col" className="p-3">Prix unitaire</th>
              <th scope="col" className="p-3">Sous-total</th>
            </tr>
          </thead>
          <tbody>
            {commande.lines.map((ligne, index) => (
              <tr
                key={`${ligne.productName}-${index}`}
                className="border-b border-mist-200"
              >
                <td className="p-3 text-navy-800">{ligne.productName}</td>
                <td className="p-3 text-mist-700">{formatQuantity(ligne.quantity)}</td>
                <td className="p-3 text-mist-700">
                  {formatOrderAmount(ligne.unitPrice, commande.currency)}
                </td>
                <td className="p-3 font-medium text-navy-800">
                  {formatOrderAmount(ligne.subtotal, commande.currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrapper>

      <Card className="mt-8">
        <dl className="grid gap-3 sm:max-w-sm sm:ml-auto">
          <div className="flex justify-between text-mist-700">
            <dt>Sous-total</dt>
            <dd>{formatOrderAmount(commande.amountUntaxed, commande.currency)}</dd>
          </div>
          <div className="flex justify-between text-mist-700">
            <dt>Taxes</dt>
            <dd>{formatOrderAmount(commande.amountTax, commande.currency)}</dd>
          </div>
          <div className="flex justify-between border-t border-mist-200 pt-3 text-lg font-semibold text-navy-900">
            <dt>Total</dt>
            <dd>{formatOrderAmount(commande.amountTotal, commande.currency)}</dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-mist-500 sm:text-right">
          Hors frais de livraison, communiqués selon la destination.
        </p>
      </Card>

      <h2 className="mt-8 text-lg font-semibold text-navy-900">Coordonnées</h2>
      <Card className="mt-3">
        <dl className="grid gap-4 sm:grid-cols-2">
          <Detail label="Nom" value={commande.deliveryAddress.name} />
          <Detail label="Adresse" value={commande.deliveryAddress.street} />
          <Detail label="Ville" value={commande.deliveryAddress.city} />
          <Detail label="Code postal" value={commande.deliveryAddress.zip} />
          <Detail label="Pays" value={commande.deliveryAddress.country} />
        </dl>
        <p className="mt-4 text-sm text-mist-500">
          Pour corriger ces informations,{' '}
          <Link href="/espace-client/profil" className="underline">
            rendez-vous dans votre profil
          </Link>
          .
        </p>
      </Card>
    </>
  );
}
