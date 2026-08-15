import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { LogoutButton } from '@/features/portal/LogoutButton';
import { getPortalMe } from '@/lib/portal/auth';
import { newCorrelationId } from '@/lib/logger';

/**
 * Accueil de l'espace client — volontairement minimal.
 *
 * Cette page existe pour prouver la chaîne complète : connexion → session BFF →
 * `/me` → route privée → déconnexion. Le tableau de bord métier viendra ensuite,
 * une fois cette chaîne validée.
 *
 * ## Server Component, et c'est structurel
 *
 * L'identité est obtenue côté serveur, à partir d'un cookie `HttpOnly` que le
 * navigateur ne peut pas lire. Faire de cette page un composant client obligerait
 * à exposer ces données à du JavaScript et, tôt ou tard, à les y conserver.
 *
 * Le `redirect()` ici n'est pas une redondance avec le proxy : le proxy n'a vu
 * qu'un cookie présent. C'est cet appel-ci, qui interroge réellement Odoo, qui
 * refuse une session forgée, expirée ou révoquée.
 */
export const metadata: Metadata = {
  title: 'Espace client',
  robots: { index: false, follow: false, nocache: true },
};

/** Jamais de rendu statique ni de cache : la page dépend d'une session. */
export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default async function EspaceClientPage() {
  const identity = await getPortalMe(newCorrelationId());
  if (!identity) {
    redirect('/connexion?next=%2Fespace-client');
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-16">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-navy-900">Espace client</h1>
          <p className="mt-2 text-mist-600">
            Bonjour {identity.name}
            {identity.company ? ` — ${identity.company}` : ''}.
          </p>
        </div>
        <LogoutButton />
      </header>

      <section className="rounded-xl border border-mist-300 bg-white p-6">
        <h2 className="text-lg font-semibold text-navy-800">Vos coordonnées</h2>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2">
          <Detail label="Nom" value={identity.name} />
          <Detail label="E-mail" value={identity.email} />
          <Detail label="Téléphone" value={identity.phone} />
          <Detail label="Société" value={identity.company} />
          <Detail label="Ville" value={identity.city} />
          <Detail label="Pays" value={identity.country} />
        </dl>
      </section>

      <p className="text-sm text-mist-600">
        Vos demandes, opérations, expéditions et documents seront accessibles ici
        prochainement.
      </p>
    </main>
  );
}

function Detail({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-sm text-mist-600">{label}</dt>
      <dd className="font-medium text-navy-800">{value || '—'}</dd>
    </div>
  );
}
