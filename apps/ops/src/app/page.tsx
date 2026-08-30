import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchActivity } from '@/lib/ops/activity';
import { entreesAutorisees } from '@/features/auth/capacites';
import { ActivityTimeline } from '@/features/activity/ActivityTimeline';
import { LogoutButton } from '@/features/auth/LogoutButton';
import { IndicateurSync } from '@/features/offline/IndicateurSync';

export const dynamic = 'force-dynamic';

/**
 * L'accueil.
 *
 * Il ne fait qu'une chose : prouver que la chaîne tient de bout en bout. Le
 * nom affiché ne vient ni du cookie ni d'un formulaire — il vient d'Odoo,
 * relu à l'instant. Les entrées listées viennent des capacités renvoyées par
 * Odoo, jamais d'un rôle interprété ici.
 */
export default async function PageAccueil() {
  const correlation = newCorrelationId();
  const identite = await currentIdentity(correlation).catch(() => null);
  if (!identite) redirect('/connexion');

  const entrees = entreesAutorisees(identite.capabilities);
  const session = await readOpsSession();
  const activite = session
    ? await fetchActivity(
      { limit: 5, scope: 'mine' }, session.odooSessionId, correlation,
    ).catch(() => null)
    : null;

  return (
    <main>
      <h1>Bonjour {identite.user.name}</h1>

      {/* Ce que l'appareil doit encore au CRM, avant toute autre chose. */}
      <IndicateurSync login={identite.user.login} />
      <p className="attenue">
        {identite.cash_actor_configured
          ? `Caisse : ${identite.cash_actor}`
          : 'Aucun acteur de caisse configuré.'}
      </p>

      <section aria-labelledby="mes-saisies-titre">
        <h2 id="mes-saisies-titre">MES SAISIES DU JOUR</h2>
        {activite ? (
          <ActivityTimeline
            events={activite.events}
            timezone={activite.timezone}
            empty="Aucune saisie serveur confirmée aujourd’hui."
          />
        ) : <p className="attenue">Activité momentanément indisponible.</p>}
        <Link className="retour" href="/activite">VOIR TOUT</Link>
      </section>

      {entrees.map((entree) => {
        const contenu = (
          <>
            <strong>{entree.titre}</strong>
            <p className="attenue" style={{ margin: '0.25rem 0 0' }}>
              {entree.description}
            </p>
          </>
        );
        // Une entrée sans écran reste une carte inerte : mieux vaut annoncer
        // ce qui existe que masquer ce qui viendra.
        return entree.href ? (
          <Link className="carte carte-lien" href={entree.href} key={entree.capacite}>
            {contenu}
          </Link>
        ) : (
          <section className="carte" key={entree.capacite}>{contenu}</section>
        );
      })}

      {entrees.length === 0 ? (
        <p className="attenue">Aucune opération ne vous est ouverte pour le moment.</p>
      ) : null}

      <LogoutButton />
    </main>
  );
}
