import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import {
  fetchTariffFamilies,
} from '@/lib/ops/intakes';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  OPS_INTAKE_IP,
  OPS_INTAKE_SESSION,
  checkRateLimit,
  cleIntakeIp,
  cleIntakeSession,
  getClientIp,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

function erreur(
  status: number,
  message: string,
  retryAfterSeconds = 0,
): NextResponse {
  const reponse = NextResponse.json(
    { success: false, error: message },
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

export async function GET(
  request: Request,
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  if (!origineAcceptable(request)) {
    return erreur(403, 'Requête refusée.');
  }
  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');

  for (const [cle, budget] of [
    [
      cleIntakeSession(session.odooSessionId),
      OPS_INTAKE_SESSION,
    ],
    [
      cleIntakeIp(getClientIp(request.headers)),
      OPS_INTAKE_IP,
    ],
  ] as const) {
    const etat = checkRateLimit(
      cle, budget.limite, budget.fenetreMs,
    );
    if (!etat.allowed) {
      return erreur(
        429,
        'Trop de requêtes. Réessayez dans quelques minutes.',
        etat.retryAfterSeconds,
      );
    }
  }

  try {
    const familles = await fetchTariffFamilies(
      session.odooSessionId, correlationId,
    );
    return NextResponse.json(
      {
        success: true,
        data: { tariff_families: familles },
      },
      {
        status: 200,
        headers: { 'Cache-Control': 'no-store' },
      },
    );
  } catch (cause) {
    if (
      cause instanceof OpsGatewayError
      && cause.code === 'forbidden'
    ) {
      return erreur(401, 'Session expirée.');
    }
    logger.error('ops.tariff-families.error', {
      correlationId,
      code: (
        cause instanceof OpsGatewayError
          ? cause.code
          : 'error'
      ),
    });
    return erreur(
      503, 'Service momentanément indisponible.',
    );
  }
}

