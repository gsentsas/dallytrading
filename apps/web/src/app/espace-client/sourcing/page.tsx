import Link from 'next/link';
import type { Metadata } from 'next';

import {
  EmptyState, PageHeader, Pagination, StatusBadge, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal, pageFromSearchParams } from '@/features/portal/load';
import { PAGE_SIZE, listSourcing } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Sourcing' };
export const dynamic = 'force-dynamic';

export default async function SourcingPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const page = pageFromSearchParams((await searchParams).page);
  const list = await loadPortal(() => listSourcing(page, newCorrelationId()));

  if (!list) {
    return (
      <>
        <PageHeader title="Sourcing" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Sourcing"
        description="Vos demandes de recherche de produits."
      />

      {list.items.length === 0 ? (
        <EmptyState>Vous n’avez encore aucune demande de sourcing.</EmptyState>
      ) : (
        <TableWrapper>
          <table className="w-full min-w-[40rem] border-collapse bg-white text-left">
            <caption className="sr-only">
              Liste de vos demandes de sourcing, page {page}
            </caption>
            <thead>
              <tr className="border-b border-mist-300 text-sm text-mist-600">
                <th scope="col" className="p-3">Référence</th>
                <th scope="col" className="p-3">Produit</th>
                <th scope="col" className="p-3">Quantité</th>
                <th scope="col" className="p-3">Date</th>
                <th scope="col" className="p-3">Statut</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((request) => (
                <tr key={request.reference} className="border-b border-mist-200">
                  <td className="p-3">
                    <Link
                      href={`/espace-client/sourcing/${encodeURIComponent(request.reference)}`}
                      className="font-medium text-green-800 hover:underline"
                    >
                      {request.reference}
                    </Link>
                  </td>
                  <td className="p-3 text-navy-800">{request.productName ?? '—'}</td>
                  <td className="p-3 text-navy-800">
                    {request.quantity} {request.unit ?? ''}
                  </td>
                  <td className="p-3 text-navy-800">{request.createdOn ?? '—'}</td>
                  <td className="p-3"><StatusBadge label={request.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      )}

      <Pagination
        basePath="/espace-client/sourcing"
        page={page}
        total={list.total}
        pageSize={PAGE_SIZE}
      />
    </>
  );
}
