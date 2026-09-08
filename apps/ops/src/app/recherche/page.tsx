import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { FormulaireRecherche } from '@/features/recherche/FormulaireRecherche';

export const dynamic = 'force-dynamic';

export default async function PageRecherche() {
  const identite = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_search !== true) redirect('/');

  return (
    <main className="ops-operation-page ops-search-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-blue" aria-hidden="true">⌕</span>
        <div>
          <p className="ops-eyebrow">DOSSIERS</p>
          <h1>Rechercher un dossier</h1>
          <p>Retrouvez un dossier par nom, téléphone ou référence.</p>
        </div>
      </header>
      <FormulaireRecherche />
    </main>
  );
}
