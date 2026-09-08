import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchLoadings, type DepartChargement } from '@/lib/ops/loading';
import { logger, newCorrelationId } from '@/lib/logger';
import { ListeChargements } from '@/features/chargement/ListeChargements';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

export default async function PageChargement() {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
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
    <main className="ops-operation-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      {/* La maquette donne ici le titre pleine largeur, sans carré d'icône :
          l'écran de sélection s'ouvre sur le texte, l'icône revient sur les
          cartes de départ. */}
      <header className="ops-operation-heading is-plain">
        <div>
          <p className="ops-eyebrow">DÉPARTS</p>
          <h1>Charger un départ</h1>
          <p>Sélectionnez un départ et vérifiez les colis à expédier sur le terrain.</p>
        </div>
      </header>

      {/*
        * Les trois temps du chargement, tels que l'écran les enchaîne déjà :
        * on choisit un départ, on vérifie les colis, on confirme. C'est un
        * repère de lecture, pas une commande — aucune étape ne se clique, et
        * le serveur reste seul à décider de ce qui est permis.
        */}
      <ol className="ops-stepper" aria-label="Étapes du chargement">
        <li aria-current="step"><span aria-hidden="true">1</span>Sélection</li>
        <li><span aria-hidden="true">2</span>Vérification</li>
        <li><span aria-hidden="true">3</span>Confirmation</li>
      </ol>

      {departs === null ? (
        <>
          <p className="erreur" role="alert">Impossible de charger les départs.</p>
          <Reessayer />
        </>
      ) : departs.length === 0 ? (
        <section className="ops-empty-state">
          <span aria-hidden="true">✓</span>
          <p className="attenue" data-testid="aucun-depart">
            Aucun départ à préparer pour le moment.
          </p>
        </section>
      ) : (
        <ListeChargements consolidations={departs} />
      )}
    </main>
  );
}
