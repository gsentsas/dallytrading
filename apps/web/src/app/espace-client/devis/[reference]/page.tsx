import Link from 'next/link';
import type { Metadata } from 'next';

import { QuoteDecision } from '@/features/portal/QuoteDecision';
import { Card, Detail, PageHeader, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getQuote } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Détail du devis' };
export const dynamic = 'force-dynamic';

export default async function QuoteDetailPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  // `params` est déjà décodé par Next : la référence arrive telle que le client
  // l'a tapée. Elle n'est jamais interpolée dans une requête — la DAL la
  // ré-encode pour l'URL, et Odoo la compare comme une valeur.
  const { reference } = await params;
  const quote = await loadPortal(() => getQuote(reference, newCorrelationId()));

  if (!quote) {
    return (
      <>
        <PageHeader title="Devis" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <Link href="/espace-client/devis" className="text-sm text-green-800 hover:underline">
        ← Retour aux devis
      </Link>
      <div className="mt-4">
        <PageHeader title={quote.reference} />
      </div>

      <Card>
        <QuoteDecision initialQuote={quote} />
        <dl className="grid gap-4 sm:grid-cols-2">
          <Detail label="Service" value={quote.service} />
          <Detail label="Origine" value={quote.origin} />
          <Detail label="Destination" value={quote.destination} />
          <Detail label="Quantité" value={quote.quantity} />
        </dl>
        {quote.goodsDescription && (
          <div className="mt-6">
            <h2 className="text-sm text-mist-600">Marchandise</h2>
            <p className="mt-1 whitespace-pre-line text-navy-800">
              {quote.goodsDescription}
            </p>
          </div>
        )}
      </Card>
    </>
  );
}
