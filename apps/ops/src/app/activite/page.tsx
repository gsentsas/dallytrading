import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchActivity } from '@/lib/ops/activity';
import { ActivityTimeline } from '@/features/activity/ActivityTimeline';

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

  return (
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>{team ? 'ACTIVITÉ AUJOURD’HUI' : 'MES SAISIES DU JOUR'}</h1>
      {page ? (
        <>
          <ActivityTimeline events={page.events} timezone={page.timezone} />
          {page.next_cursor ? (
            <Link className="bouton-lien" href={`/activite?cursor=${encodeURIComponent(page.next_cursor)}`}>
              CHARGER LA SUITE
            </Link>
          ) : null}
        </>
      ) : <p className="erreur">Activité momentanément indisponible.</p>}
    </main>
  );
}
