import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchConsolidations, type Consolidation } from '@/lib/ops/consolidations';
import { logger, newCorrelationId } from '@/lib/logger';
import { ListeDeparts } from '@/features/reception/ListeDeparts';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

export default async function PageReception() {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  let consolidations: Consolidation[] | null = null;
  try {
    consolidations = await fetchConsolidations(session.odooSessionId, correlationId);
  } catch (erreur) {
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      redirect('/connexion');
    }
    logger.error('ops.reception.error', {
      correlationId,
      code: erreur instanceof OpsGatewayError ? erreur.code : 'error',
    });
  }

  return (
    <main className="ops-operation-page ops-reception-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-green" aria-hidden="true">◇</span>
        <div>
          <p className="ops-eyebrow">RÉCEPTION</p>
          <h1>Réceptionner un colis</h1>
          <p>Enregistrer un colis sur un départ ouvert.</p>
        </div>
      </header>

      {consolidations === null ? (
        <>
          <p className="erreur" role="alert">Impossible de charger les départs.</p>
          <Reessayer />
        </>
      ) : consolidations.length === 0 ? (
        <section className="ops-empty-state">
          <span aria-hidden="true">◇</span>
          <p className="attenue">
            Aucune collecte aérienne ou maritime n’est ouverte actuellement.
          </p>
        </section>
      ) : (
        <>
          <div className="ops-section-heading ops-reception-section-heading">
            <h2>Choisissez le prochain départ</h2>
            <p>{consolidations.length} disponible(s)</p>
          </div>
          <ListeDeparts consolidations={consolidations} />
        </>
      )}
    </main>
  );
}
