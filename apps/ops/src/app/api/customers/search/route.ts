/**
 * `POST /api/customers/search` — retrouver un client depuis le terrain.
 *
 * Le navigateur ne joint jamais Odoo. Il poste ici ; le serveur relit le
 * cookie, présente la session de l'opérateur et relaie un résultat déjà réduit
 * à ce que le comptoir a besoin de voir.
 *
 * ## Ce que cette route ne journalise jamais
 *
 * Ni le numéro, ni l'adresse électronique, ni le nom, ni l'adresse postale, ni
 * le corps de la requête. Le journal retient la corrélation, l'issue et la
 * durée — de quoi diagnostiquer une panne, jamais de quoi reconstituer qui a
 * cherché qui.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { critereRecherche, searchCustomer } from '@/lib/ops/customers';
import { logger, newCorrelationId } from '@/lib/logger';
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

function erreur(status: number, message: string, retryAfterSeconds = 0): NextResponse {
  const reponse = NextResponse.json({ success: false, error: message }, { status });
  if (retryAfterSeconds > 0) reponse.headers.set('Retry-After', String(retryAfterSeconds));
  reponse.headers.set('Cache-Control', 'no-store');
  return reponse;
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const depart = Date.now();

  if (!origineAcceptable(request)) return erreur(403, 'Requête refusée.');
  if (!(request.headers.get('content-type') ?? '').includes('application/json')) {
    return erreur(415, 'Requête refusée.');
  }

  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');

  // La session d'abord : elle désigne le poste. L'adresse ensuite, en plafond
  // large — tout un entrepôt sort par la même.
  const cleSession = cleRechercheSession(session.odooSessionId);
  const cleIp = cleRechercheIp(getClientIp(request.headers));
  for (const [cle, budget, portee] of [
    [cleSession, OPS_RECHERCHE_SESSION, 'session'],
    [cleIp, OPS_RECHERCHE_IP, 'ip'],
  ] as const) {
    if (!peekRateLimit(cle, budget.limite).allowed) {
      logger.warn('ops.customers.throttled', { correlationId, scope: portee });
      return erreur(429, 'Trop de recherches. Réessayez dans quelques minutes.',
                    peekRateLimit(cle, budget.limite).retryAfterSeconds);
    }
  }
  checkRateLimit(cleSession, OPS_RECHERCHE_SESSION.limite, OPS_RECHERCHE_SESSION.fenetreMs);
  checkRateLimit(cleIp, OPS_RECHERCHE_IP.limite, OPS_RECHERCHE_IP.fenetreMs);

  let corps: unknown;
  try {
    corps = await request.json();
  } catch {
    return erreur(400, 'Requête invalide.');
  }

  const analyse = critereRecherche.safeParse(corps);
  if (!analyse.success) {
    // Le motif du refus n'est pas renvoyé : il décrirait le corps soumis, donc
    // une donnée personnelle.
    return erreur(400, 'Fournissez un numéro de téléphone ou une adresse e-mail.');
  }

  try {
    const resultat = await searchCustomer(analyse.data, session.odooSessionId, correlationId);
    logger.info('ops.customers.search', {
      correlationId,
      status: resultat.status,
      durationMs: Date.now() - depart,
    });
    return NextResponse.json(
      { success: true, data: resultat },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'invalid_request') {
      return erreur(400, 'Fournissez un numéro de téléphone ou une adresse e-mail.');
    }
    logger.error('ops.customers.error', { correlationId, code, durationMs: Date.now() - depart });
    return erreur(503, 'Service momentanément indisponible.');
  }
}
