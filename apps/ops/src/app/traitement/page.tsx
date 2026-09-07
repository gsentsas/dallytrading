import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchAnomalies } from '@/lib/ops/supervision';
import { ListeAnomalies } from '@/features/traitement/ListeAnomalies';

export const dynamic = 'force-dynamic';

/**
 * « À traiter » — ce qui, aujourd'hui, demande une décision humaine.
 *
 * ## Pourquoi cet écran est réservé au responsable
 *
 * Il traverse tous les dossiers de la société, y compris ceux qu'un
 * logisticien n'a pas ouverts. C'est une vue de supervision, et le modèle
 * métier la réserve à Dalanda.
 *
 * La protection est double, et pas par excès de zèle : le serveur refuse
 * `/api/v1/ops/anomalies` à qui n'a pas la capacité `supervise` — c'est **la**
 * protection — et l'écran, lui, n'affiche pas une entrée qu'il sait fermée.
 * Cacher n'est pas protéger : une requête forgée arriverait quand même au
 * serveur, qui la refuserait. L'inverse — protéger sans cacher — donnerait un
 * écran qui promet une page et rend une erreur.
 */
export default async function PageTraitement() {
  const correlation = newCorrelationId();
  const identite = await currentIdentity(correlation).catch(() => null);
  if (!identite) redirect('/connexion');
  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  if (identite.capabilities.supervise !== true) {
    return (
      <main>
        <Link className="retour" href="/">← Accueil</Link>
        <h1>À TRAITER</h1>
        <p className="alerte" data-testid="refus-supervision">
          Cette page est réservée au responsable.
        </p>
      </main>
    );
  }

  const liste = await fetchAnomalies(session.odooSessionId, correlation)
    .catch(() => null);

  return (
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>À TRAITER</h1>
      <p className="attenue">
        Ce que le CRM signale aujourd’hui et qui demande une décision.
      </p>
      {liste
        ? <ListeAnomalies liste={liste} />
        : (
          <p className="erreur" data-testid="anomalies-indisponibles">
            Liste momentanément indisponible.
          </p>
        )}
    </main>
  );
}
