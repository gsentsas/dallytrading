import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchConsolidations } from '@/lib/ops/consolidations';
import { fetchTariffFamilies } from '@/lib/ops/intakes';
import { newCorrelationId } from '@/lib/logger';
import { enRoute } from '@/features/reception/format';
import { FormulaireColis } from '@/features/reception/FormulaireColis';

export const dynamic = 'force-dynamic';

export default async function PageColis({
  searchParams,
}: {
  searchParams: Promise<{ consolidation?: string; customer?: string }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(correlationId).catch(() => null);
  if (!identite) redirect('/connexion');
  if (identite.capabilities.intake_create !== true) redirect('/');

  const { consolidation, customer } = await searchParams;
  if (!consolidation || !customer) redirect('/reception');

  const session = await readOpsSession();
  if (!session) redirect('/connexion');
  const [ouverts, familles] = await Promise.all([
    fetchConsolidations(session.odooSessionId, correlationId),
    fetchTariffFamilies(session.odooSessionId, correlationId),
  ]).catch(() => [null, null] as const);
  const depart = ouverts?.find((candidat) => candidat.reference === consolidation);
  if (ouverts && !depart) redirect('/reception');
  if (!familles) throw new Error('Service de réception momentanément indisponible.');

  return (
    <main className="ops-operation-page ops-reception-form-page">
      <Link
        className="retour ops-back-link"
        href={`/reception/client?consolidation=${encodeURIComponent(consolidation)}`}
      >
        ← Changer de client
      </Link>

      <header className="ops-operation-heading compact">
        <span className="ops-operation-heading-icon tone-green" aria-hidden="true">◇</span>
        <div>
          <p className="ops-eyebrow">RÉCEPTION</p>
          <h2 className="ops-visual-title">Réceptionner un colis</h2>
          <p>Enregistrer un colis sur le départ sélectionné.</p>
        </div>
      </header>

      <h1 className="sr-only">DOSSIER EN COURS</h1>
      <section className="carte ops-reception-context">
        <div>
          <small>Client</small>
          <strong data-testid="client-selectionne">Client sélectionné</strong>
        </div>
        <div>
          <small>Départ</small>
          <strong className="reference" data-testid="consolidation-selectionnee">{consolidation}</strong>
          {depart ? <span>{enRoute(depart.origin, depart.destination)}</span> : null}
        </div>
      </section>

      <FormulaireColis
        consolidation={consolidation}
        customer={customer}
        familles={familles}
        login={identite.user.login}
      />
    </main>
  );
}
