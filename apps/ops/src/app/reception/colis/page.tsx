import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

/**
 * La saisie du colis, à l'étape suivante.
 *
 * Les deux références arrivent par l'URL, et l'une comme l'autre sont opaques :
 * une référence métier pour le départ, un jeton aléatoire pour le client. Cette
 * page les porte, elle ne les croit pas — la création du dossier résoudra le
 * jeton côté serveur, revérifiera la société, l'état de la collecte et le mode
 * de transport, et appliquera la tarification serveur.
 */
export default async function PageColis({
  searchParams,
}: {
  searchParams: Promise<{ consolidation?: string; customer?: string }>;
}) {
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const { consolidation, customer } = await searchParams;
  if (!consolidation || !customer) redirect('/reception');

  return (
    <main>
      <Link
        className="retour"
        href={`/reception/client?consolidation=${encodeURIComponent(consolidation)}`}
      >
        ← Changer de client
      </Link>
      <h1>Détail du colis</h1>
      <section className="carte">
        <p className="attenue" style={{ margin: '0 0 0.25rem' }}>Départ</p>
        <p className="reference" data-testid="consolidation-selectionnee">{consolidation}</p>
        <p className="attenue" style={{ margin: '0.75rem 0 0.25rem' }}>Client</p>
        <p className="reference" data-testid="client-selectionne">{customer}</p>
      </section>
      <p className="attenue">Cette étape n’est pas encore disponible.</p>
    </main>
  );
}
