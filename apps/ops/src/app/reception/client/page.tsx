import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchConsolidations } from '@/lib/ops/consolidations';
import { newCorrelationId } from '@/lib/logger';
import { enRoute } from '@/features/reception/format';
import { RechercheClient } from '@/features/reception/RechercheClient';

export const dynamic = 'force-dynamic';

export default async function PageReceptionClient({
  searchParams,
}: {
  searchParams: Promise<{ consolidation?: string }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const { consolidation } = await searchParams;
  if (!consolidation) redirect('/reception');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  const ouverts = await fetchConsolidations(session.odooSessionId, correlationId).catch(() => null);
  const depart = ouverts?.find((candidat) => candidat.reference === consolidation);
  if (ouverts && !depart) redirect('/reception');

  return (
    <main className="ops-operation-page ops-customer-select-page">
      <Link className="retour ops-back-link" href="/reception">← Changer de départ</Link>
      <header className="ops-operation-heading compact">
        <span className="ops-operation-heading-icon tone-green" aria-hidden="true">◇</span>
        <div>
          <p className="ops-eyebrow">RÉCEPTION</p>
          <h1>Réceptionner un colis</h1>
          <p>Identifiez le client concerné avant de saisir le colis.</p>
        </div>
      </header>

      <section className="carte ops-selected-depart">
        <small>Départ sélectionné</small>
        <p className="reference">{consolidation}</p>
        {depart ? <p className="route">{enRoute(depart.origin, depart.destination)}</p> : null}
      </section>

      <div className="ops-section-heading"><h2>Identifier le client</h2><p>ÉTAPE 2</p></div>
      <RechercheClient consolidation={consolidation} />
    </main>
  );
}
