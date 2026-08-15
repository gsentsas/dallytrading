import Link from 'next/link';
import type { Metadata } from 'next';

import {
  EmptyState, PageHeader, Pagination, StatusBadge, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal, pageFromSearchParams } from '@/features/portal/load';
import { PAGE_SIZE, listTrades } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Trading' };
export const dynamic = 'force-dynamic';

export default async function TradingPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const page = pageFromSearchParams((await searchParams).page);
  const list = await loadPortal(() => listTrades(page, newCorrelationId()));

  if (!list) {
    return (
      <>
        <PageHeader title="Trading" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Trading"
        description="Vos opérations commerciales et leur avancement."
      />

      {list.items.length === 0 ? (
        <EmptyState>Vous n’avez encore aucune opération commerciale.</EmptyState>
      ) : (
        <TableWrapper>
          <table className="w-full min-w-[44rem] border-collapse bg-white text-left">
            <caption className="sr-only">
              Liste de vos opérations commerciales, page {page}
            </caption>
            <thead>
              <tr className="border-b border-mist-300 text-sm text-mist-600">
                <th scope="col" className="p-3">Référence</th>
                <th scope="col" className="p-3">Objet</th>
                <th scope="col" className="p-3">Type</th>
                <th scope="col" className="p-3">Montant</th>
                <th scope="col" className="p-3">Statut</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((trade) => (
                <tr key={trade.reference} className="border-b border-mist-200">
                  <td className="p-3">
                    <Link
                      href={`/espace-client/trading/${encodeURIComponent(trade.reference)}`}
                      className="font-medium text-green-800 hover:underline"
                    >
                      {trade.reference}
                    </Link>
                  </td>
                  <td className="p-3 text-navy-800">{trade.subject}</td>
                  <td className="p-3 text-navy-800">{trade.operationTypeLabel}</td>
                  <td className="p-3 text-navy-800">
                    {trade.saleTotal} {trade.currency ?? ''}
                  </td>
                  <td className="p-3"><StatusBadge label={trade.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      )}

      <Pagination
        basePath="/espace-client/trading"
        page={page}
        total={list.total}
        pageSize={PAGE_SIZE}
      />
    </>
  );
}
