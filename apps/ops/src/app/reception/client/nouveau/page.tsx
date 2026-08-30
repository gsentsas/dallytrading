import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { FormulaireClient } from '@/features/reception/FormulaireClient';

export const dynamic = 'force-dynamic';

/**
 * Créer un client.
 *
 * La consolidation n'entre pas dans la création : un contact CRM n'a rien à
 * voir avec un départ. Elle est seulement portée à travers l'écran pour que
 * l'opérateur retrouve son fil ensuite. Le futur enregistrement du dossier
 * revalidera l'ensemble côté serveur.
 */
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
      <FormulaireClient consolidation={consolidation} />
    </main>
  );
}
