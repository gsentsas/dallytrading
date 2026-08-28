import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { entreesAutorisees } from '@/features/auth/capacites';
import { LogoutButton } from '@/features/auth/LogoutButton';

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
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identite) redirect('/connexion');

  const entrees = entreesAutorisees(identite.capabilities);

  return (
    <main>
      <h1>Bonjour {identite.user.name}</h1>
      <p className="attenue">
        {identite.cash_actor_configured
          ? `Caisse : ${identite.cash_actor}`
          : 'Aucun acteur de caisse configuré.'}
      </p>

      {entrees.map((entree) => (
        <section className="carte" key={entree.capacite}>
          <strong>{entree.titre}</strong>
          <p className="attenue" style={{ margin: '0.25rem 0 0' }}>
            {entree.description}
          </p>
        </section>
      ))}

      {entrees.length === 0 ? (
        <p className="attenue">Aucune opération ne vous est ouverte pour le moment.</p>
      ) : null}

      <LogoutButton />
    </main>
  );
}
