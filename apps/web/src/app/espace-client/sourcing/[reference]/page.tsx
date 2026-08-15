import Link from 'next/link';
import type { Metadata } from 'next';

import { Card, Detail, PageHeader, StatusBadge, UnavailableState } from '@/features/portal/ui';
import { loadPortal } from '@/features/portal/load';
import { getSourcing } from '@/lib/portal/business';
import { newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = { title: 'Détail du sourcing' };
export const dynamic = 'force-dynamic';

/**
 * Détail d'une demande de sourcing, propositions comprises.
 *
 * Les propositions viennent de `_dally_portal_detail_payload()`, où un `search`
 * sous l'identité du client applique la record rule : celle-ci n'admet que les
 * états `sent`, `accepted`, `rejected`, `expired`. Une proposition en brouillon
 * est donc absente de la réponse, et non filtrée ici — le frontend n'a aucun
 * moyen d'en voir une, ce qui est précisément l'intention.
 *
 * Ce qui n'existe nulle part dans cette page ni dans son type : les fournisseurs
 * consultés, leurs offres, leurs prix, leurs scores, la base de coût et la marge.
 */
export default async function SourcingDetailPage({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const { reference } = await params;
  const request = await loadPortal(() => getSourcing(reference, newCorrelationId()));

  if (!request) {
    return (
      <>
        <PageHeader title="Sourcing" />
        <UnavailableState />
      </>
    );
  }

  return (
    <>
      <Link href="/espace-client/sourcing" className="text-sm text-green-800 hover:underline">
        ← Retour au sourcing
      </Link>
      <div className="mt-4">
        <PageHeader title={request.reference} />
      </div>

      <Card className="mb-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <StatusBadge label={request.status} />
          <span className="text-sm text-mist-600">
            Déposée le {request.createdOn ?? '—'}
          </span>
        </div>
        <dl className="grid gap-4 sm:grid-cols-2">
          <Detail label="Produit" value={request.productName} />
          <Detail label="Référence produit" value={request.productReference} />
          <Detail
            label="Quantité"
            value={`${request.quantity} ${request.unit ?? ''}`.trim()}
          />
        </dl>
      </Card>

      <section aria-labelledby="propositions">
        <h2 id="propositions" className="mb-4 text-lg font-semibold text-navy-800">
          Propositions reçues
        </h2>

        {request.proposals.length === 0 ? (
          <Card>
            <p className="text-mist-600">
              Aucune proposition ne vous a encore été envoyée pour cette demande.
            </p>
          </Card>
        ) : (
          <ul className="space-y-4">
            {request.proposals.map((proposal) => (
              <li key={proposal.reference}>
                <Card>
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <span className="font-semibold text-navy-900">
                      {proposal.reference}
                    </span>
                    <StatusBadge label={proposal.status} />
                  </div>
                  <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                    <Detail label="Produit" value={proposal.productName} />
                    <Detail
                      label="Quantité"
                      value={`${proposal.quantity} ${proposal.unit ?? ''}`.trim()}
                    />
                    <Detail
                      label="Prix unitaire"
                      value={`${proposal.unitPrice} ${proposal.currency ?? ''}`.trim()}
                    />
                    <Detail
                      label="Total"
                      value={`${proposal.total} ${proposal.currency ?? ''}`.trim()}
                    />
                    <Detail label="Valable jusqu’au" value={proposal.validUntil} />
                    <Detail
                      label="Livraison estimée"
                      value={proposal.estimatedDelivery}
                    />
                  </dl>
                  {proposal.commercialTerms && (
                    <div className="mt-4">
                      <h3 className="text-sm text-mist-600">Conditions</h3>
                      <p className="mt-1 whitespace-pre-line text-navy-800">
                        {proposal.commercialTerms}
                      </p>
                    </div>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
