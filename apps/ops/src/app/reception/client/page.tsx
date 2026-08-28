import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchConsolidations } from '@/lib/ops/consolidations';
import { newCorrelationId } from '@/lib/logger';
import { enRoute } from '@/features/reception/format';
import { RechercheClient } from '@/features/reception/RechercheClient';

export const dynamic = 'force-dynamic';

/**
 * Identifier le client, une fois le départ choisi.
 *
 * La référence de consolidation arrive par l'URL. Elle est **revérifiée ici**
 * contre la liste des départs encore ouverts : une URL se recopie, une
 * collecte se ferme, et rien ne garantit qu'un lien collé hier désigne encore
 * un départ où l'on peut déposer un colis. Si elle n'y est plus, on renvoie au
 * choix du départ plutôt que d'afficher un en-tête mensonger.
 *
 * Cette revérification est un confort d'écran, pas une autorisation : la
 * création du dossier refera l'ensemble des contrôles côté serveur.
 */
export default async function PageReceptionClient({
  searchParams,
}: {
  searchParams: Promise<{ consolidation?: string }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const { consolidation } = await searchParams;
  if (!consolidation) redirect('/reception');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  const ouverts = await fetchConsolidations(session.odooSessionId, correlationId).catch(() => null);
  const depart = ouverts?.find((candidat) => candidat.reference === consolidation);
  if (ouverts && !depart) redirect('/reception');

  return (
    <main>
      <Link className="retour" href="/reception">← Changer de départ</Link>
      <h1>Réceptionner un colis</h1>

      <section className="carte">
        <p className="reference">{consolidation}</p>
        {depart ? (
          <p className="route" style={{ margin: '0.15rem 0 0' }}>
            {enRoute(depart.origin, depart.destination)}
          </p>
        ) : null}
      </section>

      <h2 style={{ fontSize: '1.15rem', margin: '1.5rem 0 0.75rem' }}>Identifier le client</h2>
      <RechercheClient consolidation={consolidation} />
    </main>
  );
}
