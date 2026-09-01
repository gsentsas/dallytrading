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
import { PhotosDossier } from '@/features/reception/PhotosDossier';

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
  const activite = await fetchIntakeActivity(
    dossier.reference, { limit: 10 }, session.odooSessionId, correlationId,
  ).catch(() => null);

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

      {/* L'état et l'étape suivante, tels que le serveur les autorise. La
          liste vient de lui : l'écran n'en déduit aucune. */}
      <EtatDossier
        reference={dossier.reference}
        state={dossier.state}
        allowedTransitions={dossier.allowed_transitions}
        peutAvancer={identite.capabilities.intake_state_advance === true}
      />

      {/* Le reçu n'existe que pour un dossier que le serveur a numéroté :
          l'accès passe donc par la référence qu'il a attribuée. */}
      <Link
        className="bouton-lien"
        href={`/reception/dossier/${encodeURIComponent(dossier.reference)}/recu`}
      >
        VOIR LE REÇU
      </Link>

      {/* Le collecteur vient de l'identité serveur, jamais d'une saisie. */}
      <DossierArticles
        dossier={dossier}
        familles={familles}
        canaux={canaux}
        collecteur={identite.cash_actor ?? ''}
      />

      {/* Les preuves de terrain : après les articles qu'elles documentent,
          avant le journal qui les consigne. */}
      <PhotosDossier
        reference={dossier.reference}
        etat={dossier.state}
        peutGerer={identite.capabilities.photo_manage === true}
      />

      <section aria-labelledby="activite-dossier-titre">
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
    </main>
  );
}
