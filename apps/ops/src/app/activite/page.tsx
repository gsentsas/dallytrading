import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchActivity } from '@/lib/ops/activity';
import { OpsCardIcon } from '@/features/shell/OpsCardIcon';
import { ActivityTimeline } from '@/features/activity/ActivityTimeline';
import { IndicateurSync } from '@/features/offline/IndicateurSync';

export const dynamic = 'force-dynamic';

export default async function ActivityPage({
  searchParams,
}: {
  readonly searchParams: Promise<{ cursor?: string }>;
}) {
  const correlation = newCorrelationId();
  const identity = await currentIdentity(correlation).catch(() => null);
  if (!identity) redirect('/connexion');
  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  const { cursor } = await searchParams;
  const team = identity.capabilities.supervise === true;
  const page = await fetchActivity({
    limit: 25,
    scope: team ? 'team' : 'mine',
    ...(cursor ? { cursor } : {}),
  }, session.odooSessionId, correlation).catch(() => null);
  const titreAccessible = team ? 'ACTIVITÉ AUJOURD’HUI' : 'MES SAISIES DU JOUR';

  return (
    <main className="ops-operation-page ops-supervision-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>

      <header className="ops-supervision-heading">
        <p className="ops-eyebrow">{team ? 'SUPERVISION' : 'ACTIVITÉ'}</p>
        <h1 aria-label={titreAccessible}>{team ? 'Suivi de l’équipe 👥' : 'Mes saisies du jour'}</h1>
        <p>{team ? 'Vue d’ensemble des opérations confirmées en temps réel' : 'Vos opérations confirmées par le CRM aujourd’hui'}</p>
      </header>

      <div className="ops-supervision-status">
        <span className="ops-date-pill">Aujourd’hui</span>
        <IndicateurSync login={identity.user.login} />
      </div>

      {page ? (
        <>
          {/*
            * Un seul indicateur, et il est vrai.
            *
            * La maquette en aligne six — dossiers, colis, kilos, départs,
            * arrivées, encaissements — avec leur écart de la veille. Le
            * serveur n'expose rien de tel : il rend une page d'événements
            * confirmés. Fabriquer les cinq autres donnerait un tableau de bord
            * crédible et faux, ce qui est pire que pas de tableau de bord.
            * Le compte affiché est donc celui de cette page, et il le dit.
            */}
          <section className="ops-supervision-summary">
            <div>
              <span className="ops-card-icon tone-purple" aria-hidden="true">
                <OpsCardIcon name="supervision" />
              </span>
              <small>{team ? 'Activité équipe' : 'Mes événements'}</small>
              <strong>{page.events.length}</strong>
              <p>événement(s) confirmé(s) sur cette page</p>
            </div>
          </section>

          <section className="ops-supervision-activity" aria-labelledby="activite-recente-titre">
            <div className="ops-section-heading">
              <h2 id="activite-recente-titre">ACTIVITÉ RÉCENTE</h2>
              <p>{team ? 'ÉQUIPE' : 'MES SAISIES'}</p>
            </div>
            {page.events.length === 0 ? (
              /*
               * L'attente n'est pas une panne.
               *
               * Un écran vide laissait l'opérateur devant une phrase seule et
               * un grand blanc, sans savoir s'il manquait quelque chose. La
               * carte dit les trois choses utiles : rien n'est encore
               * confirmé, ce n'est pas une erreur, et voici quand cela
               * changera.
               */
              <section className="ops-empty-premium" data-testid="activite-vide">
                <span className="ops-card-icon tone-purple" aria-hidden="true">
                  <OpsCardIcon name="supervision" />
                </span>
                <h3>Aucune activité confirmée</h3>
                <p>
                  {team
                    ? 'Les opérations de l’équipe apparaîtront ici dès que le CRM les aura confirmées.'
                    : 'Vos saisies apparaîtront ici dès que le CRM les aura confirmées.'}
                </p>
                <p className="attenue">
                  Rien à corriger : cet écran ne montre que ce que le serveur a déjà enregistré.
                </p>
              </section>
            ) : (
              <ActivityTimeline events={page.events} timezone={page.timezone} />
            )}
          </section>

          {page.next_cursor ? (
            <Link className="bouton-lien ops-supervision-more" href={`/activite?cursor=${encodeURIComponent(page.next_cursor)}`}>
              CHARGER LA SUITE
            </Link>
          ) : null}
        </>
      ) : <p className="erreur">Activité momentanément indisponible.</p>}
    </main>
  );
}
