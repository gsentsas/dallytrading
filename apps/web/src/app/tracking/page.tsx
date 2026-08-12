import type { Metadata } from 'next';
import { headers } from 'next/headers';
import { TrackingResult } from '@/features/tracking/TrackingResult';
import { getOdooGateway } from '@/services/odoo';
import { OdooGatewayError, type PublicShipment } from '@/services/odoo/types';
import { checkRateLimit, getClientIp } from '@/lib/rate-limit';
import { logger, newCorrelationId } from '@/lib/logger';

export const metadata: Metadata = {
  title: 'Suivre mon expédition',
  description:
    'Suivez votre expédition DallyTrading en saisissant votre référence de suivi. ' +
    'Statut, trajet, dates de départ et d’arrivée estimée.',
  alternates: { canonical: '/tracking' },
  robots: { index: false, follow: false },
};

/** Always rendered on demand: a tracking result must never be cached or shared. */
export const dynamic = 'force-dynamic';

/** Shape a reference must have, mirroring the check in the Odoo controller. */
const REFERENCE_RE = /^DT-SHP-\d{4}-\d{6}$/;

/** Lookups allowed per IP per minute. */
const LOOKUP_LIMIT = 10;
const LOOKUP_WINDOW_MS = 60_000;

type Outcome =
  | { kind: 'idle' }
  | { kind: 'found'; shipment: PublicShipment }
  | { kind: 'not_found' }
  | { kind: 'malformed' }
  | { kind: 'token_missing' }
  | { kind: 'rate_limited' }
  | { kind: 'unavailable' };

/**
 * Public tracking page (§44, §90).
 *
 * Deliberately a plain HTML form submitted with GET, rendered on the server:
 *
 * * it works with JavaScript disabled and on a poor connection — which matters
 *   for this audience;
 * * a result is linkable and reloadable;
 * * no client bundle is needed for the core function of the page.
 *
 * The lookup happens server-side, so the Odoo API key never approaches the
 * browser, and the result page is marked `noindex`: a search engine must not
 * archive customers' shipment statuses.
 */
export default async function TrackingPage({
  searchParams,
}: {
  searchParams: Promise<{ ref?: string; t?: string }>;
}) {
  const params = await searchParams;
  const raw = (params.ref ?? '').trim();
  const normalised = raw.replace(/\s+/g, '').toUpperCase();
  const token = (params.t ?? '').trim();

  const outcome = await resolve(normalised, token);

  return (
    <main id="contenu" className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-bold text-navy-800 sm:text-4xl">
        Suivre mon expédition
      </h1>
      <p className="mt-4 text-mist-600">
        Utilisez le lien de suivi complet reçu par e-mail ou WhatsApp. Il contient
        votre référence, au format
        <span className="font-mono"> DT-SHP-2026-000124</span>, ainsi qu’un code de
        suivi qui protège votre expédition.
      </p>

      {/* GET, so the result is bookmarkable and the page needs no JavaScript. */}
      <form method="GET" action="/tracking" className="mt-8">
        <label htmlFor="ref" className="block font-medium text-navy-800">
          Référence de suivi
        </label>
        <div className="mt-2 flex flex-wrap gap-3">
          <input
            id="ref"
            name="ref"
            type="text"
            defaultValue={raw}
            required
            autoComplete="off"
            spellCheck={false}
            placeholder="DT-SHP-2026-000124"
            aria-invalid={
              outcome.kind === 'malformed' || outcome.kind === 'not_found'
                ? true
                : undefined
            }
            aria-describedby={outcome.kind === 'idle' ? undefined : 'tracking-message'}
            className="min-w-64 flex-1 rounded-lg border border-mist-300 p-3 font-mono"
          />
          {/* The token travels with the form so a customer can correct a typo in
              the reference without going back to their e-mail. It is never
              displayed: a code visible on screen ends up in screenshots. */}
          <input type="hidden" name="t" value={token} />
          <button
            type="submit"
            className="rounded-lg bg-green-500 px-6 py-3 font-semibold text-white hover:bg-green-600"
          >
            Rechercher
          </button>
        </div>
      </form>

      {outcome.kind !== 'idle' && outcome.kind !== 'found' && (
        <div
          id="tracking-message"
          role="alert"
          className="mt-6 rounded-lg border border-mist-300 bg-mist-100 p-4 text-navy-800"
        >
          {message(outcome.kind)}
        </div>
      )}

      {outcome.kind === 'found' && <TrackingResult shipment={outcome.shipment} />}

      <p className="mt-12 text-sm text-mist-600">
        Une question sur votre expédition ? Contactez-nous en indiquant votre
        référence : nos équipes retrouveront votre dossier immédiatement.
      </p>
    </main>
  );
}

function message(kind: Exclude<Outcome['kind'], 'idle' | 'found'>): string {
  switch (kind) {
    case 'malformed':
      return 'Cette référence n’a pas le format attendu. Vérifiez votre saisie : elle ressemble à DT-SHP-2026-000124.';
    case 'token_missing':
      return 'Pour consulter une expédition, utilisez le lien de suivi complet qui vous a été envoyé par e-mail ou WhatsApp. La référence seule ne suffit pas : cette restriction protège les expéditions de nos clients.';
    case 'not_found':
      // Wrong token and unknown reference give the same answer, on purpose: the
      // page must not confirm which references exist.
      return 'Aucune expédition ne correspond à cette référence et à ce code de suivi. Vérifiez le lien reçu, ou contactez-nous en indiquant votre référence.';
    case 'rate_limited':
      return 'Trop de recherches successives. Merci de patienter une minute avant de réessayer.';
    case 'unavailable':
      return 'Le suivi est momentanément indisponible. Merci de réessayer dans quelques minutes.';
  }
}

async function resolve(reference: string, token: string): Promise<Outcome> {
  if (!reference) {
    return { kind: 'idle' };
  }

  // Reject the obviously wrong shape before spending a round trip on it, and
  // before it can consume the caller's rate-limit budget.
  if (!REFERENCE_RE.test(reference)) {
    return { kind: 'malformed' };
  }

  // The reference alone is deliberately not enough. References are sequential, so
  // accepting them on their own would let the whole series be walked. Answered
  // before any lookup, so a walker learns nothing and spends no budget.
  if (!token) {
    return { kind: 'token_missing' };
  }

  const correlationId = newCorrelationId();
  const requestHeaders = await headers();
  const clientIp = getClientIp(requestHeaders);

  // Rate limiting matters more here than on most pages: references are
  // sequential, so an unthrottled endpoint could be walked. The payload holds
  // nothing confidential, but bulk enumeration is still worth preventing.
  const limit = checkRateLimit(
    `tracking:${clientIp}`, LOOKUP_LIMIT, LOOKUP_WINDOW_MS,
  );
  if (!limit.allowed) {
    logger.warn('Tracking lookup rate limited', { correlationId, clientIp });
    return { kind: 'rate_limited' };
  }

  try {
    const shipment = await getOdooGateway().getShipmentByTracking(
      reference, token, correlationId,
    );
    if (!shipment) {
      logger.info('Tracking lookup miss', { correlationId, reference });
      return { kind: 'not_found' };
    }
    logger.info('Tracking lookup hit', { correlationId, reference });
    return { kind: 'found', shipment };
  } catch (error) {
    // An ERP failure must not read as "your shipment does not exist": the
    // customer would stop looking for a shipment that is in fact on its way.
    if (error instanceof OdooGatewayError) {
      logger.error('Tracking lookup failed', {
        correlationId,
        clientIp,
        odooCode: error.code,
        odooRequestId: error.odooRequestId,
      });
    } else {
      logger.error('Unexpected tracking failure', {
        correlationId,
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return { kind: 'unavailable' };
  }
}
