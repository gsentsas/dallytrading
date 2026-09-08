import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchAnomalies } from '@/lib/ops/supervision';
import { ListeAnomalies } from '@/features/traitement/ListeAnomalies';

export const dynamic = 'force-dynamic';

export default async function PageTraitement() {
  const correlation = newCorrelationId();
  const identite = await currentIdentity(correlation).catch(() => null);
  if (!identite) redirect('/connexion');
  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  if (identite.capabilities.supervise !== true) {
    return (
      <main className="ops-operation-page ops-treatment-page">
        <Link className="retour ops-back-link" href="/">← Accueil</Link>
        <header className="ops-operation-heading">
          <span className="ops-operation-heading-icon tone-orange" aria-hidden="true">!</span>
          <div><p className="ops-eyebrow">SUPERVISION</p><h1>À TRAITER</h1><p>Les éléments qui demandent une décision humaine.</p></div>
        </header>
        <p className="alerte" data-testid="refus-supervision">Cette page est réservée au responsable.</p>
      </main>
    );
  }

  const liste = await fetchAnomalies(session.odooSessionId, correlation).catch(() => null);

  return (
    <main className="ops-operation-page ops-treatment-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-orange" aria-hidden="true">!</span>
        <div>
          <p className="ops-eyebrow">SUPERVISION</p>
          <h1>À TRAITER</h1>
          <p>Ce que le CRM signale aujourd’hui et qui demande une décision.</p>
        </div>
      </header>
      {liste
        ? <ListeAnomalies liste={liste} />
        : <p className="erreur" data-testid="anomalies-indisponibles">Liste momentanément indisponible.</p>}
    </main>
  );
}
