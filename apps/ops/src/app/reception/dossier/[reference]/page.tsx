import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchIntake } from '@/lib/ops/intake-lines';
import { fetchTariffFamilies } from '@/lib/ops/intakes';
import { fetchPaymentChannels } from '@/lib/ops/payments';
import { newCorrelationId } from '@/lib/logger';
import { DossierArticles } from '@/features/reception/DossierArticles';

export const dynamic = 'force-dynamic';

/**
 * Le dossier d'une réception, avec ses articles.
 *
 * Tout ce qui s'affiche vient du serveur — les totaux comme la permission de
 * modifier. L'écran ne réinvente aucune règle : il lit `editable` et
 * `edit_block_reason`.
 */
export default async function PageDossier({
  params,
}: {
  params: Promise<{ reference: string }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');

  const { reference } = await params;
  const dossier = await fetchIntake(
    decodeURIComponent(reference), session.odooSessionId, correlationId,
  ).catch(() => null);
  if (!dossier) redirect('/reception');

  const familles = await fetchTariffFamilies(
    session.odooSessionId, correlationId,
  ).catch(() => []);
  const canaux = await fetchPaymentChannels(
    session.odooSessionId, correlationId,
  ).catch(() => []);

  return (
    <main>
      <Link className="retour" href="/reception">← Réceptions</Link>
      <h1>DOSSIER {dossier.local_reference}</h1>
      <section className="carte">
        <p className="route" style={{ margin: 0 }}>{dossier.customer.name}</p>
        <p className="reference">{dossier.reference}</p>
        <p className="attenue" style={{ margin: 0 }}>
          {dossier.consolidation_reference}
        </p>
      </section>

      {/* Le collecteur vient de l'identité serveur, jamais d'une saisie. */}
      <DossierArticles
        dossier={dossier}
        familles={familles}
        canaux={canaux}
        collecteur={identite.cash_actor ?? ''}
      />
    </main>
  );
}
