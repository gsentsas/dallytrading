import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchLoadings, type DepartChargement } from '@/lib/ops/loading';
import { logger, newCorrelationId } from '@/lib/logger';
import { ListeChargements } from '@/features/chargement/ListeChargements';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

/**
 * Le choix du départ à préparer.
 *
 * Il ne répond qu'à une question : « où en sont mes départs ? ». La liste et
 * son ordre viennent du serveur ; l'écran n'offre aucun moyen d'ouvrir, de
 * clore ou de faire partir un départ — cela reste une décision de
 * back-office.
 */
export default async function PageChargement() {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');

  // La capacité, pas le rôle : c'est Odoo qui décide qui prépare un départ.
  if (identite.capabilities.consolidation_load !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  let departs: readonly DepartChargement[] | null = null;
  try {
    departs = (await fetchLoadings(session.odooSessionId, correlationId)).consolidations;
  } catch (erreur) {
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      redirect('/connexion');
    }
    logger.error('ops.chargement.error', {
      correlationId,
      code: erreur instanceof OpsGatewayError ? erreur.code : 'error',
    });
  }

  return (
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>Charger un départ</h1>

      {departs === null ? (
        <>
          {/* Aucun détail technique : ni modèle, ni code, ni trace. */}
          <p className="erreur" role="alert">Impossible de charger les départs.</p>
          <Reessayer />
        </>
      ) : departs.length === 0 ? (
        <p className="attenue" data-testid="aucun-depart">
          Aucun départ à préparer pour le moment.
        </p>
      ) : (
        <ListeChargements consolidations={departs} />
      )}
    </main>
  );
}
