import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

/**
 * L'étape suivante, encore vide.
 *
 * La référence choisie voyage dans l'URL. Ce n'est pas un problème de
 * sécurité tant qu'on tient une règle : **elle sera revalidée par le serveur**
 * au moment de créer le dossier. Le fait que le navigateur l'ait obtenue de
 * `/api/v1/ops/consolidations` ne prouve rien plus tard — une collecte se
 * ferme, une consolidation part, et une URL se recopie. Rien ici ne suppose
 * que la référence est encore ouverte, ni même qu'elle existe : la page se
 * contente de la porter.
 */
export default async function PageReceptionClient({
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
      <Link className="retour" href="/reception">← Changer de départ</Link>
      <h1>Rechercher le client</h1>
      <section className="carte">
        <p className="attenue" style={{ margin: '0 0 0.25rem' }}>Départ sélectionné</p>
        <p className="reference" data-testid="consolidation-selectionnee">{consolidation}</p>
      </section>
      <p className="attenue">Cette étape n’est pas encore disponible.</p>
    </main>
  );
}
