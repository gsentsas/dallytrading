import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { FormulaireRecherche } from '@/features/recherche/FormulaireRecherche';

export const dynamic = 'force-dynamic';

/**
 * Retrouver un dossier.
 *
 * Le seul écran de Dally Ops dont le point de départ est ce que le client dit,
 * et non ce que l'application sait déjà. Rien n'est cherché ici : la page
 * authentifie, puis laisse le formulaire interroger le serveur.
 */
export default async function PageRecherche() {
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_search !== true) redirect('/');

  return (
    <main>
      <Link className="retour" href="/">← Accueil</Link>
      <h1>RECHERCHER UN DOSSIER</h1>
      <FormulaireRecherche />
    </main>
  );
}
