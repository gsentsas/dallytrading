import Link from 'next/link';
import { redirect } from 'next/navigation';

import {
  currentIdentity,
  readOpsSession,
} from '@/lib/auth/auth';
import { fetchConsolidations } from '@/lib/ops/consolidations';
import {
  fetchTariffFamilies,
} from '@/lib/ops/intakes';
import { newCorrelationId } from '@/lib/logger';
import { enRoute } from '@/features/reception/format';
import {
  FormulaireColis,
} from '@/features/reception/FormulaireColis';

export const dynamic = 'force-dynamic';

export default async function PageColis({
  searchParams,
}: {
  searchParams: Promise<{
    consolidation?: string;
    customer?: string;
  }>;
}) {
  const correlationId = newCorrelationId();
  const identite = await currentIdentity(
    correlationId,
  ).catch(() => null);
  if (!identite) redirect('/connexion');
  if (
    identite.capabilities.intake_create !== true
  ) redirect('/');

  const { consolidation, customer } = await searchParams;
  if (!consolidation || !customer) {
    redirect('/reception');
  }

  const session = await readOpsSession();
  if (!session) redirect('/connexion');
  const [ouverts, familles] = await Promise.all([
    fetchConsolidations(
      session.odooSessionId, correlationId,
    ),
    fetchTariffFamilies(
      session.odooSessionId, correlationId,
    ),
  ]).catch(() => [null, null] as const);
  const depart = ouverts?.find(
    (candidat) => candidat.reference === consolidation,
  );
  if (ouverts && !depart) redirect('/reception');
  if (!familles) {
    throw new Error(
      'Service de réception momentanément indisponible.',
    );
  }

  return (
    <main>
      <Link
        className="retour"
        href={`/reception/client?consolidation=${encodeURIComponent(consolidation)}`}
      >
        ← Changer de client
      </Link>
      <h1>DOSSIER EN COURS</h1>
      <section className="carte">
        <p
          className="attenue"
          style={{ margin: '0 0 0.25rem' }}
        >
          Client
        </p>
        {/*
          La référence client est un jeton opaque : utile au serveur,
          illisible pour un opérateur. L'afficher n'aiderait personne au
          comptoir.

          Afficher le nom demanderait soit de le faire voyager dans l'URL —
          donc une donnée personnelle dans les journaux du proxy —, soit
          d'ouvrir une lecture de `res.partner` que cette étape n'accorde
          pas. On annonce donc simplement qu'un client est sélectionné.
        */}
        <p data-testid="client-selectionne">
          Client sélectionné
        </p>
        <p
          className="attenue"
          style={{ margin: '0.75rem 0 0.25rem' }}
        >
          Départ
        </p>
        <p
          className="reference"
          data-testid="consolidation-selectionnee"
        >
          {consolidation}
        </p>
        {depart ? (
          <p className="route">
            {enRoute(depart.origin, depart.destination)}
          </p>
        ) : null}
      </section>
      <FormulaireColis
        consolidation={consolidation}
        customer={customer}
        familles={familles}
      />
    </main>
  );
}
