import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchExpenseConsolidations, type DepartDepense } from '@/lib/ops/expenses';
import { logger, newCorrelationId } from '@/lib/logger';
import { ListeDepartsDepense } from '@/features/depenses/ListeDepartsDepense';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

/**
 * Le choix du départ, pour une dépense.
 *
 * Écran distinct de celui des réceptions, et non un filtre de plus sur le
 * même : les deux ne montrent pas les mêmes départs. On ne réceptionne un
 * colis que pendant la collecte, mais on paie un dédouanement après le départ
 * et un stockage à l'arrivée. Servir une liste unique aux deux écrans
 * forcerait l'un des deux à mentir.
 */
export default async function PageDepenses() {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');

  // La capacité, pas le rôle : c'est Odoo qui décide qui déclare une dépense.
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
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>Déclarer une dépense</h1>

      {!identite.cash_actor_configured ? (
        <p className="erreur" role="alert">
          Votre compte n’est pas encore configuré pour la caisse. Demandez à un
          responsable avant de déclarer une dépense.
        </p>
      ) : null}

      {departs === null ? (
        <>
          {/* Aucun détail technique : ni modèle, ni code, ni trace. */}
          <p className="erreur" role="alert">Impossible de charger les départs.</p>
          <Reessayer />
        </>
      ) : departs.length === 0 ? (
        <p className="attenue">Aucun départ aérien ou maritime n’est actif actuellement.</p>
      ) : (
        <>
          <p className="attenue">Choisissez le départ concerné</p>
          <ListeDepartsDepense departs={departs} />
        </>
      )}
    </main>
  );
}
