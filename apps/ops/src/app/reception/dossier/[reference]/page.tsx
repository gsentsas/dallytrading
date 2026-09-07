import Link from 'next/link';
import { redirect } from 'next/navigation';

import { currentIdentity, readOpsSession } from '@/lib/auth/auth';
import { fetchIntake } from '@/lib/ops/intake-lines';
import { fetchTariffFamilies } from '@/lib/ops/intakes';
import { fetchPaymentChannels } from '@/lib/ops/payments';
import { fetchIntakeActivity } from '@/lib/ops/activity';
import { newCorrelationId } from '@/lib/logger';
import { ActivityTimeline } from '@/features/activity/ActivityTimeline';
import { DossierArticles } from '@/features/reception/DossierArticles';
import { EtatDossier } from '@/features/reception/EtatDossier';
import { SynchronisationDossier } from '@/features/reception/SynchronisationDossier';
import { PhotosDossier } from '@/features/reception/PhotosDossier';
import { EvenementsDossier } from '@/features/reception/EvenementsDossier';

export const dynamic = 'force-dynamic';

function initiales(nom: string): string {
  return nom.split(/\s+/).filter(Boolean).slice(0, 2)
    .map((partie) => partie.slice(0, 1).toUpperCase()).join('') || 'DT';
}

function dateLisible(value: string | null): string {
  if (!value) return 'Non renseignée';
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'long' }).format(date);
}

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
  const activite = await fetchIntakeActivity(
    dossier.reference, { limit: 10 }, session.odooSessionId, correlationId,
  ).catch(() => null);

  return (
    <main className="ops-operation-page ops-dossier-page">
      <Link className="retour ops-back-link" href="/reception">← Réceptions</Link>
      <header className="ops-dossier-heading">
        <p className="ops-eyebrow">DOSSIER</p>
        <h1>DOSSIER {dossier.local_reference}</h1>
      </header>

      <section className="carte ops-dossier-customer">
        <span className="ops-dossier-avatar" aria-hidden="true">{initiales(dossier.customer.name)}</span>
        <div>
          <strong>{dossier.customer.name}</strong>
          <small>{dossier.reference}</small>
        </div>
        <span className="ops-dossier-state">En cours</span>
      </section>

      <section className="carte ops-dossier-information">
        <div className="ops-dossier-section-title">
          <span className="tone-blue" aria-hidden="true">▤</span>
          <h2>Informations du dossier</h2>
        </div>
        <dl>
          <div><dt>Référence</dt><dd>{dossier.local_reference}</dd></div>
          <div><dt>Date de réception</dt><dd>{dateLisible(dossier.received_on)}</dd></div>
          <div><dt>Nombre d’articles</dt><dd>{dossier.totals.lines_count}</dd></div>
          <div><dt>Poids total</dt><dd>{new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(dossier.totals.weight_kg)} kg</dd></div>
          <div><dt>Volume total</dt><dd>{new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 3 }).format(dossier.totals.volume_cbm)} m³</dd></div>
          <div><dt>Départ</dt><dd>{dossier.consolidation_reference}</dd></div>
        </dl>
      </section>

      <EtatDossier
        reference={dossier.reference}
        state={dossier.state}
        allowedTransitions={dossier.allowed_transitions}
        peutAvancer={identite.capabilities.intake_state_advance === true}
      />

      <Link
        className="bouton-lien ops-dossier-receipt"
        href={`/reception/dossier/${encodeURIComponent(dossier.reference)}/recu`}
      >
        VOIR LE REÇU
      </Link>

      <DossierArticles
        dossier={dossier}
        familles={familles}
        canaux={canaux}
        collecteur={identite.cash_actor ?? ''}
      />

      <PhotosDossier
        reference={dossier.reference}
        etat={dossier.state}
        peutGerer={identite.capabilities.photo_manage === true}
      />

      <SynchronisationDossier etat={dossier.reconciliation} />
      <section className="ops-dossier-activity" aria-labelledby="activite-dossier-titre">
        <h2 id="activite-dossier-titre">ACTIVITÉ</h2>
        {activite ? (
          <>
            <ActivityTimeline events={activite.events} timezone={activite.timezone} />
            {activite.next_cursor ? (
              <Link className="retour" href="/activite">VOIR PLUS D’ACTIVITÉ</Link>
            ) : null}
          </>
        ) : <p className="attenue">Activité momentanément indisponible.</p>}
      </section>

      <EvenementsDossier
        reference={dossier.reference}
        peutConsigner={identite.capabilities.event_create === true}
      />
    </main>
  );
}
