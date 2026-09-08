import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { newCorrelationId } from '@/lib/logger';
import { fetchTransferOptions, fetchTransfers } from '@/lib/ops/transfers';
import { TransfertsCaisse } from '@/features/caisse/TransfertsCaisse';

export const dynamic = 'force-dynamic';

export default async function Page() {
  const identity = await currentIdentity(newCorrelationId()).catch(() => null);
  if (!identity) redirect('/connexion');
  if (!identity.capabilities.transfer_create) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');
  const correlation = newCorrelationId();
  const [options, initial] = await Promise.all([
    fetchTransferOptions(session.odooSessionId, correlation),
    fetchTransfers(session.odooSessionId, correlation),
  ]);

  return (
    <main className="ops-operation-page ops-transfer-page">
      <Link className="retour ops-back-link" href="/">← Accueil</Link>
      <header className="ops-operation-heading">
        <span className="ops-operation-heading-icon tone-teal" aria-hidden="true">⇄</span>
        <div>
          <p className="ops-eyebrow">CAISSE</p>
          <h1>Transfert de caisse</h1>
          <p>Transmettre des fonds à un autre opérateur, avec confirmation de réception.</p>
        </div>
      </header>
      <TransfertsCaisse initial={initial} options={options} />
    </main>
  );
}
