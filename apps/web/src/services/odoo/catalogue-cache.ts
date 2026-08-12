/**
 * Cached access to the service catalogue.
 *
 * Odoo is the source of truth (`GET /api/v1/services`) and the website keeps no
 * business list of its own. That creates a dependency the quote form cannot
 * survive without, so this module makes the dependency safe:
 *
 * * **Fresh** for `TTL_MS` — the catalogue changes when someone edits it in Odoo,
 *   which is rare, so a short TTL costs nothing and keeps a change propagating in
 *   minutes.
 * * **Stale-on-error** — if Odoo is unreachable and we hold a previous copy, it is
 *   served with a warning rather than failing the page. A form built from a
 *   ten-minute-old catalogue is correct; a form that will not load is not.
 * * **Single in-flight fetch** — concurrent requests share one call, so a cold
 *   cache under load does not become a stampede against Odoo.
 * * **Honest failure** — with no copy at all and Odoo down, it fails. There is
 *   deliberately no hardcoded fallback list: that would be the second independent
 *   business list this design exists to remove, and it would silently serve wrong
 *   services after any catalogue change.
 *
 * In-process, so it resets on deploy and is not shared between instances. That is
 * acceptable for a catalogue: the cost of a miss is one API call.
 */

import { logger } from '@/lib/logger';
import { getOdooGateway } from '@/services/odoo';
import { OdooGatewayError, type ServiceType } from '@/services/odoo/types';

/** How long a fetched catalogue is considered fresh. */
const TTL_MS = 5 * 60 * 1000;

/** How long a stale copy may still be served when Odoo is unreachable. */
const MAX_STALE_MS = 24 * 60 * 60 * 1000;

interface CacheEntry {
  services: ReadonlyArray<ServiceType>;
  fetchedAt: number;
}

let cache: CacheEntry | null = null;
let inFlight: Promise<ReadonlyArray<ServiceType>> | null = null;

export interface CatalogueResult {
  readonly services: ReadonlyArray<ServiceType>;
  /** True when Odoo could not be reached and a previous copy is being served. */
  readonly stale: boolean;
}

/**
 * Return the catalogue, from cache when fresh.
 *
 * @throws OdooGatewayError when Odoo is unreachable and no usable copy is held.
 */
export async function getServiceCatalogue(
  correlationId: string,
): Promise<CatalogueResult> {
  const now = Date.now();

  if (cache && now - cache.fetchedAt < TTL_MS) {
    return { services: cache.services, stale: false };
  }

  try {
    // Share one fetch between concurrent callers.
    inFlight ??= getOdooGateway()
      .listServiceTypes(correlationId)
      .finally(() => {
        inFlight = null;
      });

    const services = await inFlight;

    // An empty catalogue is treated as a failure rather than cached: it would
    // render a quote form with no service to choose, and the likeliest cause is a
    // misconfiguration, not a company that offers nothing.
    if (services.length === 0) {
      throw new OdooGatewayError(
        'internal_error',
        'The ERP returned an empty service catalogue.',
        502,
      );
    }

    cache = { services, fetchedAt: now };
    return { services, stale: false };
  } catch (error) {
    if (cache && now - cache.fetchedAt < MAX_STALE_MS) {
      logger.warn('Serving a stale service catalogue', {
        correlationId,
        ageSeconds: Math.round((now - cache.fetchedAt) / 1000),
        error: error instanceof Error ? error.message : String(error),
      });
      return { services: cache.services, stale: true };
    }

    logger.error('Service catalogue unavailable and no usable copy held', {
      correlationId,
      error: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

/** Drop the cache. Test-only, and usable by a future admin revalidation hook. */
export function invalidateServiceCatalogue(): void {
  cache = null;
  inFlight = null;
}

/** Seed the cache. Test-only. */
export function primeServiceCatalogue(
  services: ReadonlyArray<ServiceType>,
  fetchedAt = Date.now(),
): void {
  cache = { services, fetchedAt };
}
