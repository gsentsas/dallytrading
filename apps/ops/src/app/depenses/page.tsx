import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchExpenseConsolidations, type DepartDepense } from '@/lib/ops/expenses';
import { logger, newCorrelationId } from '@/lib/logger';
import { ListeDepartsDepense } from '@/features/depenses/ListeDepartsDepense';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

export default async function PageDepenses() {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.expense_create !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  let departs: DepartDepense[] | null = null;
  try {
    departs = await fetchExpenseConsolidations(session.odooSessionId, correlationId);
  } catch (erreur) {
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      redirect('/connexion');
    }
    logger.error('ops.depenses.error', {
      correlationId,
      code: erreur instanceof OpsGatewayError ? erreur.code : 'error',
    });
  }

  return (
    <main className="ops-operation-page ops-expense-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-red" aria-hidden="true">●●</span>
        <div>
          <p className="ops-eyebrow">CAISSE</p>
          <h1>Déclarer une dépense</h1>
          <p>Enregistrer une dépense engagée sur le terrain.</p>
        </div>
      </header>

      {!identite.cash_actor_configured ? (
        <p className="erreur" role="alert">
          Votre compte n’est pas encore configuré pour la caisse. Demandez à un
          responsable avant de déclarer une dépense.
        </p>
      ) : null}

      {departs === null ? (
        <>
          <p className="erreur" role="alert">Impossible de charger les départs.</p>
          <Reessayer />
        </>
      ) : departs.length === 0 ? (
        <section className="ops-empty-state">
          <span aria-hidden="true">✓</span>
          <p className="attenue">Aucun départ aérien ou maritime n’est actif actuellement.</p>
        </section>
      ) : (
        <>
          <div className="ops-section-heading"><h2>Choisissez le départ concerné</h2><p>{departs.length} disponible(s)</p></div>
          <ListeDepartsDepense departs={departs} />
        </>
      )}
    </main>
  );
}
