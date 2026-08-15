import Link from 'next/link';
import type { Metadata } from 'next';

import {
  EmptyState, PageHeader, Pagination, StatusBadge, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal, pageFromSearchParams } from '@/features/portal/load';
import { PAGE_SIZE, listQuotes } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Devis' };
export const dynamic = 'force-dynamic';

export default async function QuotesPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const page = pageFromSearchParams((await searchParams).page);
  const list = await loadPortal(() => listQuotes(page, newCorrelationId()));

  if (!list) {
    return (
      <>
        <PageHeader title="Devis" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Devis"
        description="Vos demandes de devis et leur avancement."
      />

      {list.items.length === 0 ? (
        <EmptyState>Vous n’avez encore aucune demande de devis.</EmptyState>
      ) : (
        <TableWrapper>
          <table className="w-full min-w-[44rem] border-collapse bg-white text-left">
            <caption className="sr-only">
              Liste de vos demandes de devis, page {page}
            </caption>
            <thead>
              <tr className="border-b border-mist-300 text-sm text-mist-600">
                <th scope="col" className="p-3">Référence</th>
                <th scope="col" className="p-3">Service</th>
                <th scope="col" className="p-3">Trajet</th>
                <th scope="col" className="p-3">Date</th>
                <th scope="col" className="p-3">Statut</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((quote) => (
                <tr key={quote.reference} className="border-b border-mist-200">
                  <td className="p-3">
                    <Link
                      href={`/espace-client/devis/${encodeURIComponent(quote.reference)}`}
                      className="font-medium text-green-800 hover:underline"
                    >
                      {quote.reference}
                    </Link>
                  </td>
                  <td className="p-3 text-navy-800">{quote.service ?? '—'}</td>
                  <td className="p-3 text-navy-800">
                    {quote.origin ?? '—'} → {quote.destination ?? '—'}
                  </td>
                  <td className="p-3 text-navy-800">{quote.createdOn ?? '—'}</td>
                  <td className="p-3"><StatusBadge label={quote.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      )}

      <Pagination
        basePath="/espace-client/devis"
        page={page}
        total={list.total}
        pageSize={PAGE_SIZE}
      />
    </>
  );
}
