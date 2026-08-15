import Link from 'next/link';
import type { Metadata } from 'next';

import { Card, Detail, PageHeader, StatusBadge, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getTrade } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Détail de l’opération' };
export const dynamic = 'force-dynamic';

/**
 * Détail d'une opération — le volet VENTE, et lui seul.
 *
 * Une opération de trading a deux contreparties : un fournisseur d'un côté, le
 * client de l'autre. `saleTotal` est ce que le client doit ; le sous-total
 * d'achat, les coûts, les commissions et la marge décrivent l'autre volet. Ils ne
 * sont pas masqués ici : ils portent `groups=` côté Odoo, ils sont absents de la
 * projection, et ils n'existent pas dans `PortalTrade`.
 */
export default async function TradeDetailPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const trade = await loadPortal(() => getTrade(reference, newCorrelationId()));

  if (!trade) {
    return (
      <>
        <PageHeader title="Trading" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <Link href="/espace-client/trading" className="text-sm text-green-800 hover:underline">
        ← Retour au trading
      </Link>
      <div className="mt-4">
        <PageHeader title={trade.reference} description={trade.subject} />
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <StatusBadge label={trade.status} />
          <span className="text-sm text-mist-600">{trade.operationTypeLabel}</span>
        </div>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Detail
            label="Montant"
            value={`${trade.saleTotal} ${trade.currency ?? ''}`.trim()}
          />
          <Detail label="Origine" value={trade.origin} />
          <Detail label="Destination" value={trade.destination} />
          <Detail label="Clôture prévue" value={trade.expectedClose} />
          <Detail label="Ouverte le" value={trade.createdOn} />
        </dl>
      </Card>
    </>
  );
}
