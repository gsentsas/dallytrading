import Link from 'next/link';
import { notFound, redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { normaliserReferenceDepart } from '@/lib/ops/loading';
import { newCorrelationId } from '@/lib/logger';
import { ChargementDepart } from '@/features/chargement/ChargementDepart';

export const dynamic = 'force-dynamic';

export default async function PageChargementDepart(
  { params }: { params: Promise<{ reference: string }> },
) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.consolidation_load !== true) redirect('/');

  const { reference } = await params;
  const propre = normaliserReferenceDepart(reference);
  if (propre === null) notFound();

  return (
    <main className="ops-operation-page ops-loading-page">
      <Link className="retour ops-back-link" href="/chargement">← Départs</Link>
      <header className="ops-operation-heading compact">
        <span className="ops-operation-heading-icon tone-orange" aria-hidden="true">▣</span>
        <div>
          <p className="ops-eyebrow">CHARGEMENT</p>
          <h1>Charger un départ</h1>
          <p>Vérifiez ce qui part et confirmez chaque colis physique.</p>
        </div>
      </header>
      <p className="ops-loading-reference">Référence départ <strong>{propre}</strong></p>
      <ChargementDepart reference={propre} />
    </main>
  );
}
