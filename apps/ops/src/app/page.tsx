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

const iconByEntry: Record<string, string> = {
  recherche: '⌕',
  reception: '◇',
  chargement: '⇥',
  encaissement: '▣',
  depenses: '◫',
  transferts: '⇄',
  agenda: '▦',
  supervision: '👥',
  traitement: '!',
};

const toneByEntry: Record<string, string> = {
  recherche: 'blue',
  reception: 'green',
  chargement: 'orange',
  encaissement: 'purple',
  depenses: 'red',
  transferts: 'cyan',
  agenda: 'blue',
  supervision: 'purple',
  traitement: 'red',
};

export default async function PageAccueil() {
  const correlation = newCorrelationId();
  const identite = await currentIdentity(correlation).catch(() => null);
  if (!identite) redirect('/connexion');

  const entrees = entreesAutorisees(identite.capabilities);
  const session = await readOpsSession();
  const activite = session
    ? await fetchActivity(
      { limit: 4, scope: 'mine' }, session.odooSessionId, correlation,
    ).catch(() => null)
    : null;

  return (
    <main className="ops-home">
      <section className="ops-home-intro">
        <p className="ops-eyebrow">BONJOUR</p>
        <div className="ops-home-title-row">
          <div>
            <h1>Bonjour {identite.user.name} <span aria-hidden="true">👋</span></h1>
            <div className="ops-status-row">
              <IndicateurSync login={identite.user.login} />
              <span className="ops-pill ops-pill-neutral">
                <span aria-hidden="true">♙</span>
                {identite.cash_actor_configured
                  ? `Caisse : ${identite.cash_actor}`
                  : 'Caisse non configurée'}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="ops-home-activity" aria-labelledby="mes-saisies-titre">
        <div className="ops-card-icon tone-blue" aria-hidden="true">▤</div>
        <div className="ops-home-activity-copy">
          <h2 id="mes-saisies-titre">Mes saisies du jour</h2>
          {activite ? (
            activite.events.length > 0 ? (
              <ActivityTimeline
                events={activite.events.slice(0, 1)}
                timezone={activite.timezone}
                empty="Aucune saisie serveur confirmée aujourd’hui."
              />
            ) : <p>Aucune saisie serveur confirmée aujourd’hui.</p>
          ) : <p>Activité momentanément indisponible.</p>}
        </div>
        <Link className="ops-outline-button" href="/activite">Voir tout <span aria-hidden="true">→</span></Link>
      </section>

      <section className="ops-quick-section" aria-labelledby="acces-rapide-titre">
        <div className="ops-section-heading">
          <h2 id="acces-rapide-titre">ACCÈS RAPIDE</h2>
          <p>TOUT POUR VOS OPÉRATIONS</p>
        </div>

        <div className="ops-quick-grid">
          {entrees.filter((entree) => entree.id !== 'traitement').map((entree) => {
            const content = (
              <>
                <div className={`ops-card-icon tone-${toneByEntry[entree.id] ?? 'blue'}`} aria-hidden="true">
                  {iconByEntry[entree.id] ?? '•'}
                </div>
                <div className="ops-quick-copy">
                  <strong>{entree.titre}</strong>
                  <p>{entree.description}</p>
                </div>
                <span className="ops-card-chevron" aria-hidden="true">›</span>
              </>
            );

            return entree.href ? (
              <Link className="ops-quick-card" href={entree.href} key={entree.id}>{content}</Link>
            ) : (
              <section className="ops-quick-card" key={entree.id}>{content}</section>
            );
          })}
        </div>
      </section>

      <Link className="ops-insight-card" href="/activite">
        <span className="ops-insight-icon" aria-hidden="true">▥</span>
        <span>
          <strong>Une logistique plus fluide sur le terrain</strong>
          <small>DallyTrading vous accompagne au quotidien</small>
        </span>
        <span className="ops-card-chevron" aria-hidden="true">›</span>
      </Link>

      <div className="ops-home-secondary-actions">
        <LogoutButton />
      </div>
    </main>
  );
}
