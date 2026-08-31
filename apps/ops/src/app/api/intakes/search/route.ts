/**
 * `GET /api/intakes/search` — retrouver un dossier depuis le comptoir.
 *
 * Le navigateur ne joint jamais Odoo. Il interroge cette route ; le serveur
 * relit le cookie, présente la session de l'opérateur et relaie un résultat
 * déjà réduit à ce que le comptoir a besoin de voir.
 *
 * ## Ce que cette route ne journalise jamais
 *
 * Ni la requête, ni les noms, ni les numéros trouvés. Le journal retient la
 * corrélation, le nombre de résultats et la durée — de quoi diagnostiquer une
 * lenteur, jamais de quoi reconstituer qui a cherché qui.
 *
 * ## Pourquoi un plafond ici alors qu'Odoo en a un
 *
 * Ce n'est pas une redite : le plafond d'Odoo protège la base, celui-ci
 * protège la session. Une recherche est une surface d'énumération, et le
 * durcissement ne doit jamais dépendre du navigateur qui l'appelle.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { logger, newCorrelationId } from '@/lib/logger';
import { searchIntakes } from '@/lib/ops/intake-search';
import {
  OPS_RECHERCHE_IP,
  OPS_RECHERCHE_SESSION,
  checkRateLimit,
  cleRechercheIp,
  cleRechercheSession,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

// Pas de `cursor` : la recherche rend une page bornée et un drapeau. Le
// laisser passer inviterait un jour à republier une clé de parcours.
const AUTORISES = new Set(['q', 'limit']);
const LONGUEUR_MAXIMALE = 64;

function reponse(corps: unknown, status: number, retryAfterSeconds = 0): NextResponse {
  const sortie = NextResponse.json(corps, {
    status,
    headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
  if (retryAfterSeconds > 0) sortie.headers.set('Retry-After', String(retryAfterSeconds));
  return sortie;
}

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].some((cle) => !AUTORISES.has(cle))) {
    return reponse({ success: false, error: 'Filtre invalide.' }, 400);
  }

  const q = url.searchParams.get('q');
  if (q === null || q.trim() === '' || q.length > LONGUEUR_MAXIMALE) {
    return reponse({ success: false, error: 'Indiquez ce que vous cherchez.' }, 400);
  }

  const limitTexte = url.searchParams.get('limit');
  const limit = limitTexte === null ? undefined : Number(limitTexte);
  if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 50)) {
    return reponse({ success: false, error: 'Filtre invalide.' }, 400);
  }

  const session = await readOpsSession();
  if (!session) return reponse({ success: false, error: 'Session expirée.' }, 401);

  // La session d'abord : elle désigne le poste. L'adresse ensuite, en plafond
  // large — tout un comptoir sort par la même.
  const cleSession = cleRechercheSession(session.odooSessionId);
  const cleIp = cleRechercheIp(getClientIp(request.headers));
  for (const [cle, budget] of [
    [cleSession, OPS_RECHERCHE_SESSION],
    [cleIp, OPS_RECHERCHE_IP],
  ] as const) {
    const etat = peekRateLimit(cle, budget.limite);
    if (!etat.allowed) {
      return reponse(
        { success: false, error: 'Trop de recherches. Réessayez dans quelques minutes.' },
        429, etat.retryAfterSeconds,
      );
    }
  }
  checkRateLimit(cleSession, OPS_RECHERCHE_SESSION.limite, OPS_RECHERCHE_SESSION.fenetreMs);
  checkRateLimit(cleIp, OPS_RECHERCHE_IP.limite, OPS_RECHERCHE_IP.fenetreMs);

  const correlationId = newCorrelationId();
  const depart = Date.now();
  try {
    const data = await searchIntakes(
      { q, ...(limit === undefined ? {} : { limit }) },
      session.odooSessionId,
      correlationId,
    );
    logger.info('ops.intakes.search', {
      correlationId, count: data.items.length, durationMs: Date.now() - depart,
    });
    return reponse({ success: true, data }, 200);
  } catch (erreur) {
    const code = erreur instanceof OpsGatewayError ? erreur.code : 'error';
    if (code === 'forbidden') return reponse({ success: false, error: 'Session expirée.' }, 401);
    if (code === 'invalid_request') {
      // Le refus d'Odoo — requête trop courte, plafond invalide — se relaie
      // tel quel : lui seul connaît la règle.
      return reponse({ success: false, error: 'Précisez votre recherche.' }, 400);
    }
    logger.error('ops.intakes.search.error', {
      correlationId, code, durationMs: Date.now() - depart,
    });
    return reponse({ success: false, error: 'Service momentanément indisponible.' }, 503);
  }
}
