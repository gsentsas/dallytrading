/**
 * Accès mis en cache aux référentiels publics.
 *
 * ## Pourquoi un cache et pas un appel par visiteur
 *
 * Un port n'ouvre pas deux fois par jour. Interroger Odoo à chaque ouverture du
 * formulaire ferait payer à chaque visiteur une latence pour une réponse
 * identique, et à l'ERP une charge qui ne lui apprend rien.
 *
 * La politique reprend exactement celle du catalogue des services — cinq
 * minutes de fraîcheur, une copie périmée servie jusqu'à vingt-quatre heures si
 * Odoo devient injoignable. Ce dernier point est le plus important : un
 * formulaire qui s'ouvre avec une liste de ports vieille d'une heure est utile,
 * un formulaire qui ne s'ouvre pas ne l'est pas.
 *
 * ## Ce qui n'est pas mis en cache
 *
 * Les subdivisions. Elles se demandent par pays, il y en a plus de deux mille,
 * et un cache par pays retiendrait de la mémoire pour des pays que personne ne
 * choisira. Elles passent par la route BFF, qui a son propre cache HTTP.
 */

import { logger } from '@/lib/logger';
import { getOdooGateway } from '@/services/odoo';
import { OdooGatewayError } from '@/services/odoo/types';
import {
  referenceCountrySchema,
  referenceIncotermSchema,
  referenceLocationSchema,
  type ReferenceCountry,
  type ReferenceIncoterm,
  type ReferenceLocation,
} from '@/lib/references/dto';

const TTL_MS = 5 * 60 * 1000;
const MAX_STALE_MS = 24 * 60 * 60 * 1000;

export interface PublicReferences {
  readonly countries: ReadonlyArray<ReferenceCountry>;
  readonly locations: ReadonlyArray<ReferenceLocation>;
  readonly incoterms: ReadonlyArray<ReferenceIncoterm>;
  /** Vrai quand Odoo était injoignable et qu'une copie antérieure est servie. */
  readonly stale: boolean;
}

interface CacheEntry {
  countries: ReadonlyArray<ReferenceCountry>;
  locations: ReadonlyArray<ReferenceLocation>;
  incoterms: ReadonlyArray<ReferenceIncoterm>;
  fetchedAt: number;
}

let cache: CacheEntry | null = null;
let inFlight: Promise<CacheEntry> | null = null;

/** Ne garde que les entrées conformes ; une ligne inattendue est écartée, pas fatale. */
function valider<T>(
  entries: ReadonlyArray<unknown>,
  schema: { safeParse: (value: unknown) => { success: boolean; data?: T } },
  kind: string,
  correlationId: string,
): ReadonlyArray<T> {
  const valides: T[] = [];
  let rejetees = 0;
  for (const entry of entries) {
    const resultat = schema.safeParse(entry);
    if (resultat.success && resultat.data !== undefined) {
      valides.push(resultat.data);
    } else {
      rejetees += 1;
    }
  }
  if (rejetees > 0) {
    // Une entrée rejetée signale un écart entre ce qu'Odoo publie et ce que la
    // vitrine accepte : c'est une anomalie à corriger, pas un incident à taire.
    logger.warn('references.rejected', {
      correlationId,
      kind,
      rejected: rejetees,
      kept: valides.length,
    });
  }
  return valides;
}

async function charger(correlationId: string): Promise<CacheEntry> {
  const gateway = getOdooGateway();
  const [countries, locations, incoterms] = await Promise.all([
    gateway.listReferences('countries', undefined, correlationId),
    gateway.listReferences('locations', undefined, correlationId),
    gateway.listReferences('incoterms', undefined, correlationId),
  ]);

  return {
    countries: valider(countries, referenceCountrySchema, 'countries', correlationId),
    locations: valider(locations, referenceLocationSchema, 'locations', correlationId),
    incoterms: valider(incoterms, referenceIncotermSchema, 'incoterms', correlationId),
    fetchedAt: Date.now(),
  };
}

/**
 * Les référentiels du formulaire public.
 *
 * Ne lève jamais : un formulaire sans liste de ports reste utilisable — les
 * villes restent saisissables à la main — alors qu'une page en erreur ne l'est
 * pas. Les listes vides sont donc un repli assumé, journalisé.
 */
export async function getPublicReferences(
  correlationId: string,
): Promise<PublicReferences> {
  const now = Date.now();

  if (cache && now - cache.fetchedAt < TTL_MS) {
    return { ...cache, stale: false };
  }

  try {
    inFlight ??= charger(correlationId).finally(() => {
      inFlight = null;
    });
    cache = await inFlight;
    return { ...cache, stale: false };
  } catch (error) {
    const age = cache ? now - cache.fetchedAt : Number.POSITIVE_INFINITY;
    if (cache && age < MAX_STALE_MS) {
      logger.warn('references.stale', {
        correlationId,
        ageMs: age,
        code: error instanceof OdooGatewayError ? error.code : 'unknown',
      });
      return { ...cache, stale: true };
    }
    logger.error('references.unavailable', {
      correlationId,
      code: error instanceof OdooGatewayError ? error.code : 'unknown',
    });
    return { countries: [], locations: [], incoterms: [], stale: true };
  }
}

/** Pour les tests : repart d'un cache vide. */
export function resetReferencesCache(): void {
  cache = null;
  inFlight = null;
}
