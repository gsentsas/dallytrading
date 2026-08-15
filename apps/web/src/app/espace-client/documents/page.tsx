import type { Metadata } from 'next';

import {
  EmptyState, PageHeader, Pagination, TableWrapper, UnavailableState,
} from '@/features/portal/ui';
import { loadPortal, pageFromSearchParams } from '@/features/portal/load';
import { PAGE_SIZE, listDocuments } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Documents' };
export const dynamic = 'force-dynamic';

/**
 * Documents publiés.
 *
 * Le lien de téléchargement pointe vers NOTRE route BFF, jamais vers Odoo.
 * L'identifiant de la pièce jointe n'apparaît nulle part : le connaître
 * inviterait à tenter `/web/content/<id>`, qui contournerait le contrôle. Le
 * client ne manipule que `DOC-<n>`, une poignée qui ne confère aucun droit —
 * Odoo refait la vérification à chaque téléchargement.
 */
export default async function DocumentsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const page = pageFromSearchParams((await searchParams).page);
  const list = await loadPortal(() => listDocuments(page, newCorrelationId()));

  if (!list) {
    return (
      <>
        <PageHeader title="Documents" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Documents"
        description="Les documents que DallyTrading a publiés pour vous."
      />

      {list.items.length === 0 ? (
        <EmptyState>Aucun document n’a encore été publié pour vous.</EmptyState>
      ) : (
        <TableWrapper>
          <table className="w-full min-w-[42rem] border-collapse bg-white text-left">
            <caption className="sr-only">Vos documents, page {page}</caption>
            <thead>
              <tr className="border-b border-mist-300 text-sm text-mist-600">
                <th scope="col" className="p-3">Nom</th>
                <th scope="col" className="p-3">Type</th>
                <th scope="col" className="p-3">Dossier</th>
                <th scope="col" className="p-3">Publié le</th>
                <th scope="col" className="p-3">
                  <span className="sr-only">Téléchargement</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((document) => (
                <tr key={document.reference} className="border-b border-mist-200">
                  <td className="p-3 font-medium text-navy-800">{document.name}</td>
                  <td className="p-3 text-navy-800">
                    {document.documentTypeLabel ?? '—'}
                  </td>
                  <td className="p-3 text-navy-800">
                    {document.relatedReference || document.relatedTo || '—'}
                  </td>
                  <td className="p-3 text-navy-800">{document.publishedOn ?? '—'}</td>
                  <td className="p-3">
                    <a
                      href={`/api/portal/documents/${encodeURIComponent(document.reference)}`}
                      className="rounded-lg border border-mist-300 px-3 py-2 text-sm font-medium text-navy-800 hover:bg-mist-100"
                    >
                      Télécharger
                      <span className="sr-only"> {document.name}</span>
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrapper>
      )}

      <Pagination
        basePath="/espace-client/documents"
        page={page}
        total={list.total}
        pageSize={PAGE_SIZE}
      />
    </>
  );
}
