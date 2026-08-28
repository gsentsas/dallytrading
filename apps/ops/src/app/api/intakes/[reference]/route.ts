/** `GET /api/intakes/<reference>` — le dossier et ses articles. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchIntake } from '@/lib/ops/intake-lines';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const session = await readOpsSession();
  if (!session) {
    return NextResponse.json(
      { success: false, error: 'Session expirée.' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  const { reference } = await contexte.params;
  try {
    const intake = await fetchIntake(reference, session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: { intake } },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (erreur) {
    const code = erreur instanceof OpsGatewayError ? erreur.code : 'error';
    if (code === 'forbidden') {
      return NextResponse.json(
        { success: false, error: 'Session expirée.' },
        { status: 401, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    if (code === 'not_found' || code === 'invalid_request') {
      return NextResponse.json(
        { success: false, error: 'Dossier introuvable.' },
        { status: 404, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.intake.detail.error', { correlationId, code });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
