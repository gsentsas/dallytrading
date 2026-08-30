/**
 * `GET /api/consolidations` — les départs ouverts, pour le navigateur.
 *
 * Le navigateur ne joint jamais Odoo. Il demande ici, le serveur relit le
 * cookie, présente la session de l'opérateur, et relaie une liste déjà
 * réduite à ce que le terrain a besoin de voir.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchConsolidations } from '@/lib/ops/consolidations';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const session = await readOpsSession();
  if (!session) {
    return NextResponse.json(
      { success: false, error: 'Session expirée.' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  try {
    const consolidations = await fetchConsolidations(session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: { consolidations } },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (erreur) {
    // Une session qu'Odoo ne reconnaît plus est un 401, pas une panne : le
    // navigateur doit repasser par la connexion, pas proposer « réessayer ».
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      return NextResponse.json(
        { success: false, error: 'Session expirée.' },
        { status: 401, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.consolidations.error', {
      correlationId,
      code: erreur instanceof OpsGatewayError ? erreur.code : 'error',
    });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
