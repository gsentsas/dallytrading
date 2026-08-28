/**
 * `POST /api/customers` — créer un client depuis le comptoir.
 *
 * Première écriture déclenchée par un téléphone. Tout ce qui suit est
 * organisé autour d'un fait : dans un entrepôt, une requête part et sa réponse
 * ne revient pas toujours.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { createCustomer, demandeCreation } from '@/lib/ops/customers';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  OPS_CREATION_IP,
  OPS_CREATION_SESSION,
  checkRateLimit,
  cleCreationIp,
  cleCreationSession,
  cleDemandeComptee,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

function erreur(
  status: number,
  message: string,
  code?: string,
  retryAfterSeconds = 0,
): NextResponse {
  const reponse = NextResponse.json(
    code ? { success: false, error: message, code } : { success: false, error: message },
    { status },
  );
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

  let corps: unknown;
  try {
    corps = await request.json();
  } catch {
    return erreur(400, 'Requête invalide.');
  }

  const analyse = demandeCreation.safeParse(corps);
  if (!analyse.success) {
    // Le motif décrirait le corps soumis, donc des données personnelles.
    return erreur(400, 'Vérifiez les informations saisies.');
  }

  const cleSession = cleCreationSession(session.odooSessionId);
  const cleIp = cleCreationIp(getClientIp(request.headers));
  for (const [cle, budget, portee] of [
    [cleSession, OPS_CREATION_SESSION, 'session'],
    [cleIp, OPS_CREATION_IP, 'ip'],
  ] as const) {
    const etat = peekRateLimit(cle, budget.limite);
    if (!etat.allowed) {
      logger.warn('ops.customers.create.throttled', { correlationId, scope: portee });
      return erreur(429, 'Trop de créations. Réessayez dans quelques minutes.',
                    undefined, etat.retryAfterSeconds);
    }
  }

  // Une demande n'est comptée qu'une fois, quel que soit le nombre de
  // tentatives réseau : elles portent le même identifiant et ne produiront
  // qu'une seule fiche.
  const premiere = checkRateLimit(
    cleDemandeComptee(analyse.data.request_uuid), 1, OPS_CREATION_SESSION.fenetreMs);
  if (premiere.allowed) {
    checkRateLimit(cleSession, OPS_CREATION_SESSION.limite, OPS_CREATION_SESSION.fenetreMs);
    checkRateLimit(cleIp, OPS_CREATION_IP.limite, OPS_CREATION_IP.fenetreMs);
  }

  try {
    const resultat = await createCustomer(analyse.data, session.odooSessionId, correlationId);
    logger.info('ops.customers.create', {
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
    if (code === 'invalid_request') return erreur(400, 'Vérifiez les informations saisies.');
    if (code === 'conflict') {
      const conflit = e as OpsGatewayError;
      logger.warn('ops.customers.create.conflict', {
        correlationId, code: conflit.conflictCode ?? 'unknown',
      });
      return conflit.conflictCode === 'idempotency_conflict'
        ? erreur(409,
                 'Cette demande a déjà été traitée avec d’autres informations.',
                 'idempotency_conflict')
        : erreur(409,
                 'Ces coordonnées correspondent à plusieurs fiches clients. ' +
                 'Demandez une vérification au responsable.',
                 'customer_identity_conflict');
    }
    logger.error('ops.customers.create.error', {
      correlationId, code, durationMs: Date.now() - depart,
    });
    return erreur(503, 'Service momentanément indisponible.');
  }
}
