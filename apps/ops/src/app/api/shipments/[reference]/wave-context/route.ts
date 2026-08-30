/** `GET /api/shipments/<Axxx>/wave-context` — le dossier et le bénéficiaire imposé. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchWaveContext } from '@/lib/ops/wave-payments';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const session = await readOpsSession();
  if (!session) {
    return NextResponse.json(
      { success: false, error: 'Session expirée.' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  try {
    const data = await fetchWaveContext(
      decodeURIComponent(reference), session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data },
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
    if (code === 'not_found') {
      return NextResponse.json(
        { success: false, error: 'Dossier introuvable.' },
        { status: 404, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    if (code === 'conflict') {
      // Le bénéficiaire n'est pas configuré : l'écran doit le dire plutôt que
      // d'annoncer une panne, car un responsable peut le corriger en une minute.
      logger.warn('ops.wave.context.conflict', {
        correlationId,
        code: (erreur as OpsGatewayError).conflictCode ?? 'conflict',
      });
      return NextResponse.json(
        { success: false,
          error: 'Le bénéficiaire des encaissements Wave n’est pas configuré. '
               + 'Demandez à un responsable.' },
        { status: 409, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.wave.context.error', { correlationId, code });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
