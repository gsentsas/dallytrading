import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { FormulaireClient } from '@/features/reception/FormulaireClient';

export const dynamic = 'force-dynamic';

export default async function PageNouveauClient({
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
    <main className="ops-operation-page ops-customer-create-page">
      <Link
        className="retour ops-back-link"
        href={`/reception/client?consolidation=${encodeURIComponent(consolidation)}`}
      >
        ← Rechercher à nouveau
      </Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-blue" aria-hidden="true">＋</span>
        <div>
          <p className="ops-eyebrow">CLIENT</p>
          <h1>Nouveau client</h1>
          <p>Créer la fiche CRM avant de poursuivre la réception.</p>
        </div>
      </header>
      <FormulaireClient consolidation={consolidation} />
    </main>
  );
}
