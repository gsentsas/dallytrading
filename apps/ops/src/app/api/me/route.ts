/**
 * `GET /api/me` — l'identité de l'opérateur connecté.
 *
 * Cette route interroge réellement Odoo à chaque appel : elle ne relit pas le
 * cookie pour en déduire un nom ou un rôle. Le cookie ne sert qu'à retrouver
 * la session ; c'est Odoo qui dit qui est là et ce qu'il peut faire.
 */

import { NextResponse } from 'next/server';

import { currentIdentity } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  try {
    const identite = await currentIdentity(correlationId);
    if (!identite) {
      return NextResponse.json(
        { success: false, error: 'Session expirée.' },
        { status: 401, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    return NextResponse.json(
      { success: true, data: identite },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (erreur) {
    const code = erreur instanceof OpsGatewayError ? erreur.code : 'error';
    logger.error('ops.me.error', { correlationId, code });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
