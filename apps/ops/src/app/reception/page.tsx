import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchConsolidations, type Consolidation } from '@/lib/ops/consolidations';
import { logger, newCorrelationId } from '@/lib/logger';
import { ListeDeparts } from '@/features/reception/ListeDeparts';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

/**
 * Le choix du départ.
 *
 * Premier écran métier de Dally Ops, et il ne répond qu'à une question : « sur
 * quel départ dois-je enregistrer ce colis ? » Tout ce qui n'aide pas à y
 * répondre — poids, dossiers, factures, MAWB — n'est pas demandé au serveur et
 * n'arrive donc jamais ici.
 *
 * L'écran n'offre aucun moyen d'ouvrir ou de fermer une collecte : cela reste
 * une décision de back-office. Un logisticien qui ne trouve pas son départ doit
 * appeler, pas en créer un.
 */
export default async function PageReception() {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');

  // La capacité, pas le rôle : c'est Odoo qui décide qui réceptionne.
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
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>Réceptionner un colis</h1>

      {consolidations === null ? (
        <>
          {/* Aucun détail technique : ni modèle, ni code, ni trace. */}
          <p className="erreur" role="alert">Impossible de charger les départs.</p>
          <Reessayer />
        </>
      ) : consolidations.length === 0 ? (
        <p className="attenue">
          Aucune collecte aérienne ou maritime n’est ouverte actuellement.
        </p>
      ) : (
        <>
          <p className="attenue">Choisissez le prochain départ</p>
          <ListeDeparts consolidations={consolidations} />
        </>
      )}
    </main>
  );
}
