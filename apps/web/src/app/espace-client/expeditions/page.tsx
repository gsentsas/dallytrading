import Link from 'next/link';
import type { Metadata } from 'next';

import {
  EmptyState, PageHeader, Pagination, StatusBadge, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal, pageFromSearchParams } from '@/features/portal/load';
import { PAGE_SIZE, listShipments } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Expéditions' };
export const dynamic = 'force-dynamic';

export default async function ShipmentsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const page = pageFromSearchParams((await searchParams).page);
  const list = await loadPortal(() => listShipments(page, newCorrelationId()));

  if (!list) {
    return (
      <>
        <PageHeader title="Expéditions" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Expéditions"
        description="Suivez vos envois et leur acheminement."
      />

      {list.items.length === 0 ? (
        <EmptyState>Vous n’avez encore aucune expédition.</EmptyState>
      ) : (
        <TableWrapper>
          <table className="w-full min-w-[46rem] border-collapse bg-white text-left">
            <caption className="sr-only">
              Liste de vos expéditions, page {page}
            </caption>
            <thead>
              <tr className="border-b border-mist-300 text-sm text-mist-600">
                <th scope="col" className="p-3">Référence</th>
                <th scope="col" className="p-3">Mode</th>
                <th scope="col" className="p-3">Trajet</th>
                <th scope="col" className="p-3">Arrivée estimée</th>
                <th scope="col" className="p-3">Statut</th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((shipment) => (
                <tr key={shipment.reference} className="border-b border-mist-200">
                  <td className="p-3">
                    <Link
                      href={`/espace-client/expeditions/${encodeURIComponent(shipment.reference)}`}
                      className="font-medium text-green-800 hover:underline"
                    >
                      {shipment.reference}
                    </Link>
                  </td>
                  <td className="p-3 text-navy-800">
                    {shipment.transportModeLabel ?? '—'}
                  </td>
                  <td className="p-3 text-navy-800">
                    {shipment.origin ?? '—'} → {shipment.destination ?? '—'}
                  </td>
                  <td className="p-3 text-navy-800">
                    {shipment.estimatedArrival ?? '—'}
                  </td>
                  <td className="p-3"><StatusBadge label={shipment.statusLabel} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      )}

      <Pagination
        basePath="/espace-client/expeditions"
        page={page}
        total={list.total}
        pageSize={PAGE_SIZE}
      />
    </>
  );
}
