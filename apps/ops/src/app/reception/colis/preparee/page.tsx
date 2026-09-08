import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchConsolidations } from '@/lib/ops/consolidations';
import { fetchTariffFamilies } from '@/lib/ops/intakes';
import { ReceptionPreparee } from '@/features/agenda/ReceptionPreparee';

export const dynamic = 'force-dynamic';

export default async function PageReceptionPreparee() {
  const correlation = newCorrelationId();
  const identity = await currentIdentity(correlation).catch(() => null);
  if (!identity) redirect('/connexion');
  if (identity.capabilities.intake_create !== true) redirect('/');
  const session = await readOpsSession();
  if (!session) redirect('/connexion');
  const [consolidations, families] = await Promise.all([
    fetchConsolidations(session.odooSessionId, correlation),
    fetchTariffFamilies(session.odooSessionId, correlation),
  ]);

  return (
    <main className="ops-operation-page ops-prepared-reception-page">
      <Link className="retour ops-back-link" href="/agenda">← Rendez-vous</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-green" aria-hidden="true">◇</span>
        <div>
          <p className="ops-eyebrow">AGENDA → RÉCEPTION</p>
          <h1 className="ops-visual-title">Réception préparée</h1>
          <p>Les informations du rendez-vous sont prêtes pour la saisie terrain.</p>
        </div>
      </header>
      <ReceptionPreparee consolidations={consolidations} families={families} />
    </main>
  );
}
