import Link from 'next/link';
import { notFound, redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { normaliserReferenceDepart } from '@/lib/ops/loading';
import { newCorrelationId } from '@/lib/logger';
import { ChargementDepart } from '@/features/chargement/ChargementDepart';

export const dynamic = 'force-dynamic';

/**
 * La pile d'un départ.
 *
 * La page ne lit rien elle-même : le contenu bouge à chaque geste, et une
 * page serveur rendue une fois afficherait un état périmé dès le premier
 * colis chargé. Elle vérifie la capacité, valide la référence, et confie la
 * lecture au composant qui la rechargera après chaque mutation.
 *
 * Pas de `decodeURIComponent` : App Router livre le segment déjà décodé.
 */
export default async function PageChargementDepart(
  { params }: { params: Promise<{ reference: string }> },
) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.consolidation_load !== true) redirect('/');

  const { reference } = await params;
  const propre = normaliserReferenceDepart(reference);
  if (propre === null) notFound();

  return (
    <main>
      <Link className="retour" href="/chargement">← Départs</Link>
      <h1>DÉPART {propre}</h1>
      <ChargementDepart reference={propre} />
    </main>
  );
}
