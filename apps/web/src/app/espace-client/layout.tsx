import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { PortalNav } from '@/features/portal/PortalNav';
import { getPortalMe } from '@/lib/portal/auth';
import { newCorrelationId } from '@/lib/logger';

/**
 * Coque de l'espace client.
 *
 * ## La session est vérifiée ICI, une fois
 *
 * Chaque page enfant hérite de cette garde. L'alternative — répéter
 * `requirePortalSession()` dans onze pages — tiendrait jusqu'à la douzième, celle
 * qu'on ajouterait un mardi soir sans y penser.
 *
 * Les pages appellent quand même la DAL, qui exige la session à son tour : ce
 * n'est pas une redondance mais la même règle appliquée à chaque appel réel. Le
 * layout décide s'il faut afficher quoi que ce soit ; la DAL décide si Odoo répond.
 *
 * ## Pas de mise en cache, jamais
 *
 * `force-dynamic` et `revalidate = 0` sur la coque valent pour tout ce qu'elle
 * enveloppe. Une page de ce sous-arbre rendue statiquement figerait les dossiers
 * d'un client dans un fichier servi à tout le monde.
 */
export const metadata: Metadata = {
  title: { default: 'Espace client', template: '%s | Espace client' },
  // Une page privée indexée ne peut de toute façon montrer qu'une redirection,
  // mais elle fait apparaître le portail dans les résultats pour le nom de la
  // société — une cible d'hameçonnage toute trouvée.
  robots: { index: false, follow: false, nocache: true },
};

export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';

export default async function EspaceClientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const identity = await getPortalMe(newCorrelationId());
  if (!identity) {
    redirect('/connexion?next=%2Fespace-client');
  }

  return (
    <div className="min-h-screen bg-mist-50">
      <PortalNav
        name={identity.name}
        company={identity.company}
      />
      <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </div>
    </div>
  );
}
