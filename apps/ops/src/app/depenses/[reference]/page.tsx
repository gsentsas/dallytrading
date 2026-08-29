import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchExpenses, type ListeDepenses } from '@/lib/ops/expenses';
import { logger, newCorrelationId } from '@/lib/logger';
import { DepensesDepart } from '@/features/depenses/DepensesDepart';
import { Reessayer } from '@/features/reception/Reessayer';

export const dynamic = 'force-dynamic';

/**
 * Les dépenses d'un départ.
 *
 * L'écran relit la liste à chaque chargement plutôt que de conserver un état
 * local : ce qui est affiché doit être ce qu'Odoo détient, y compris quand un
 * collègue a saisi une dépense depuis un autre téléphone.
 */
export default async function PageDepensesDepart({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const correlationId = newCorrelationId();
  const { reference } = await params;

  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.expense_create !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  let liste: ListeDepenses | null = null;
  let introuvable = false;
  try {
    liste = await fetchExpenses(reference, session.odooSessionId, correlationId);
  } catch (erreur) {
    const code = erreur instanceof OpsGatewayError ? erreur.code : 'error';
    if (code === 'forbidden') redirect('/connexion');
    if (code === 'not_found') introuvable = true;
    else logger.error('ops.depenses.depart.error', { correlationId, code });
  }

  return (
    <main>
      <Link className="retour" href="/depenses">← Départs</Link>
      <h1>Dépenses du départ</h1>
      <p className="reference">{reference}</p>

      {introuvable ? (
        <p className="erreur" role="alert">Ce départ est introuvable.</p>
      ) : liste === null ? (
        <>
          <p className="erreur" role="alert">Impossible de charger les dépenses.</p>
          <Reessayer />
        </>
      ) : (
        <DepensesDepart liste={liste} payeur={identite.cash_actor ?? '—'} />
      )}
    </main>
  );
}
