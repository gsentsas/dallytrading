import Link from 'next/link';
import type { Metadata } from 'next';

import {
  EmptyState, PageHeader, StatusBadge, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { formatOrderAmount, formatOrderDate } from '@/features/shop/order-format';
import { listShopOrders } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Commandes' };
export const dynamic = 'force-dynamic';

/**
 * Les commandes boutique du client.
 *
 * ## Lues sous sa session, jamais avec une clé d'API
 *
 * `listShopOrders` passe par `PortalOdooGateway`, donc par le cookie
 * `dt_portal_session`. Les clés `shop:read` et `shop:checkout` servent la vitrine
 * publique et la création de commande ; les faire intervenir dans une lecture
 * cloisonnée par client remplacerait le cloisonnement d'Odoo par le nôtre.
 *
 * ## Aucune commande invité ici
 *
 * Un contact invité n'a pas de compte, donc il n'est le `commercial_partner_id`
 * de personne, donc la record rule native ne le fait apparaître dans aucun
 * portail. L'absence n'est pas un filtre que nous appliquons : elle tombe de la
 * même règle que le reste.
 */
export default async function CommandesPage() {
  const liste = await loadPortal(() => listShopOrders(newCorrelationId()));

  if (!liste) {
    return (
      <>
        <PageHeader title="Commandes" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Commandes"
        description="Vos commandes passées sur la boutique en ligne."
      />

      {liste.orders.length === 0 ? (
        <EmptyState>
          Vous n’avez encore passé aucune commande sur la boutique.
        </EmptyState>
      ) : (
        <TableWrapper>
          <table className="w-full min-w-[40rem] border-collapse bg-white text-left">
            <caption className="sr-only">Liste de vos commandes boutique</caption>
            <thead>
              <tr className="border-b border-mist-300 text-sm text-mist-600">
                <th scope="col" className="p-3">Référence</th>
                <th scope="col" className="p-3">Date</th>
                <th scope="col" className="p-3">Statut</th>
                <th scope="col" className="p-3">Articles</th>
                <th scope="col" className="p-3">Total</th>
              </tr>
            </thead>
            <tbody>
              {liste.orders.map((commande) => (
                <tr key={commande.reference} className="border-b border-mist-200">
                  <td className="p-3">
                    <Link
                      href={`/espace-client/commandes/${encodeURIComponent(commande.reference)}`}
                      className="font-medium text-navy-800 underline hover:text-navy-900"
                    >
                      {commande.reference}
                    </Link>
                  </td>
                  <td className="p-3 text-mist-700">{formatOrderDate(commande.date)}</td>
                  <td className="p-3">
                    {/* Le libellé vient d'Odoo : une seule source pour ce que
                        l'état affirme au client. */}
                    <StatusBadge label={commande.stateLabel} />
                  </td>
                  <td className="p-3 text-mist-700">{commande.itemCount}</td>
                  <td className="p-3 font-medium text-navy-800">
                    {formatOrderAmount(commande.amountTotal, commande.currency)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      )}
    </>
  );
}
