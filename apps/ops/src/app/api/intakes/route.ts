import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import {
  createIntake,
  demandeIntake,
} from '@/lib/ops/intakes';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  OPS_INTAKE_IP,
  OPS_INTAKE_SESSION,
  checkRateLimit,
  cleIntakeDemande,
  cleIntakeIp,
  cleIntakeSession,
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
    code
      ? { success: false, error: message, code }
      : { success: false, error: message },
    { status },
  );
  reponse.headers.set('Cache-Control', 'no-store');
  if (retryAfterSeconds > 0) {
    reponse.headers.set(
      'Retry-After', String(retryAfterSeconds),
    );
  }
  return reponse;
}

export async function POST(
  request: Request,
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const depart = Date.now();
  if (!origineAcceptable(request)) {
    return erreur(403, 'Requête refusée.');
  }
  if (
    !(request.headers.get('content-type') ?? '')
      .includes('application/json')
  ) {
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
  const analyse = demandeIntake.safeParse(corps);
  if (!analyse.success) {
    return erreur(
      400, 'Vérifiez les informations du colis.',
    );
  }

  const cleSession = cleIntakeSession(
    session.odooSessionId,
  );
  const cleIp = cleIntakeIp(
    getClientIp(request.headers),
  );
  for (const [cle, budget, portee] of [
    [cleSession, OPS_INTAKE_SESSION, 'session'],
    [cleIp, OPS_INTAKE_IP, 'ip'],
  ] as const) {
    const etat = peekRateLimit(cle, budget.limite);
    if (!etat.allowed) {
      logger.warn('ops.intakes.throttled', {
        correlationId, scope: portee,
      });
      return erreur(
        429,
        'Trop de réceptions. Réessayez dans quelques minutes.',
        undefined,
        etat.retryAfterSeconds,
      );
    }
  }

  const premiere = checkRateLimit(
    cleIntakeDemande(analyse.data.request_uuid),
    1,
    OPS_INTAKE_SESSION.fenetreMs,
  );
  if (premiere.allowed) {
    checkRateLimit(
      cleSession,
      OPS_INTAKE_SESSION.limite,
      OPS_INTAKE_SESSION.fenetreMs,
    );
    checkRateLimit(
      cleIp,
      OPS_INTAKE_IP.limite,
      OPS_INTAKE_IP.fenetreMs,
    );
  }

  try {
    const resultat = await createIntake(
      analyse.data,
      session.odooSessionId,
      correlationId,
    );
    logger.info('ops.intakes.create', {
      correlationId,
      status: resultat.status,
      pricingStatus: resultat.intake.line.pricing_status,
      durationMs: Date.now() - depart,
    });
    return NextResponse.json(
      { success: true, data: resultat },
      {
        status: 200,
        headers: { 'Cache-Control': 'no-store' },
      },
    );
  } catch (cause) {
    const gateway = (
      cause instanceof OpsGatewayError ? cause : null
    );
    if (gateway?.code === 'forbidden') {
      return erreur(401, 'Session expirée.');
    }
    if (gateway?.code === 'invalid_request') {
      return erreur(
        400, 'Vérifiez les informations du colis.',
      );
    }
    if (gateway?.code === 'not_found') {
      return erreur(
        404,
        'Client introuvable. Recommencez la recherche.',
        'customer_not_found',
      );
    }
    if (gateway?.code === 'conflict') {
      const code = gateway.conflictCode;
      if (code === 'idempotency_conflict') {
        return erreur(
          409,
          'Cette demande a déjà été traitée avec d’autres informations.',
          code,
        );
      }
      return erreur(
        409,
        'Ce départ n’est plus ouvert à la réception.',
        'consolidation_not_open',
      );
    }
    logger.error('ops.intakes.error', {
      correlationId,
      code: gateway?.code ?? 'error',
      durationMs: Date.now() - depart,
    });
    return erreur(
      503, 'Service momentanément indisponible.',
    );
  }
}

