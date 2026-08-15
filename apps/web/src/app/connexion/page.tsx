import type { Metadata } from 'next';

import { LoginForm } from '@/features/portal/LoginForm';
import { safeNextPath } from '@/lib/portal/csrf';

/**
 * Page de connexion à l'espace client.
 *
 * `noindex, nofollow` : rien ici n'a de valeur pour un moteur, et une page de
 * connexion indexée finit dans les résultats de recherche pour le nom de la
 * société, où elle sert de cible toute trouvée aux tentatives d'hameçonnage.
 */
export const metadata: Metadata = {
  title: 'Connexion à l’espace client',
  description: 'Accédez à vos dossiers DallyTrading.',
  robots: { index: false, follow: false, nocache: true },
};

export const dynamic = 'force-dynamic';

export default async function ConnexionPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const params = await searchParams;
  const rawNext = Array.isArray(params.next) ? params.next[0] : params.next;
  // Assaini côté serveur, jamais côté client : le paramètre est fourni par
  // l'appelant, donc par un lien qu'on ne contrôle pas.
  const next = safeNextPath(rawNext);

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-8 px-4 py-16">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold text-navy-900">Espace client</h1>
        <p className="text-mist-600">
          Connectez-vous pour suivre vos demandes, vos opérations et vos
          expéditions.
        </p>
      </header>

      <LoginForm next={next} />

      <p className="text-sm text-mist-600">
        Vous n’avez pas encore d’accès ? Contactez votre interlocuteur
        DallyTrading pour l’ouverture de votre espace.
      </p>
    </main>
  );
}
