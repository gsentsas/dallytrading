import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

/** La création d'un client, à l'étape suivante. */
export default async function PageNouveauClient({
  searchParams,
}: {
  searchParams: Promise<{ consolidation?: string }>;
}) {
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const { consolidation } = await searchParams;
  if (!consolidation) redirect('/reception');

  return (
    <main>
      <Link
        className="retour"
        href={`/reception/client?consolidation=${encodeURIComponent(consolidation)}`}
      >
        ← Rechercher à nouveau
      </Link>
      <h1>Nouveau client</h1>
      <p className="attenue">Cette étape n’est pas encore disponible.</p>
    </main>
  );
}
