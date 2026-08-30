import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchReceipt } from '@/lib/ops/receipts';
import { newCorrelationId } from '@/lib/logger';
import { RecuActions } from '@/features/reception/RecuActions';
import { RecuDocument } from '@/features/reception/RecuDocument';

export const dynamic = 'force-dynamic';

/**
 * Le reçu à remettre au client.
 *
 * Le document est relu dans Odoo à l'instant où l'écran s'ouvre : jamais
 * depuis un cache local, jamais depuis une file hors connexion. Un dossier qui
 * n'a pas encore sa référence serveur n'a pas de reçu — et c'est heureux, car
 * un papier portant un numéro né dans le téléphone ne renverrait à rien.
 */
export default async function PageRecu({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  const { reference } = await params;
  const dossier = decodeURIComponent(reference);
  const recu = await fetchReceipt(
    dossier, session.odooSessionId, correlationId,
  ).catch(() => null);
  if (!recu) redirect(`/reception/dossier/${encodeURIComponent(dossier)}`);

  return (
    <main>
      <Link
        className="retour sans-impression"
        href={`/reception/dossier/${encodeURIComponent(dossier)}`}
      >
        ← RETOUR DOSSIER
      </Link>
      <RecuDocument recu={recu} />
      <div className="sans-impression">
        <RecuActions reference={recu.reference} />
      </div>
    </main>
  );
}
