/**
 * `GET|POST /api/shipments/<Axxx>/payments` — les encaissements d'un dossier.
 *
 * Le dossier est désigné par sa référence publique, jamais par un identifiant
 * interne. Le corps du POST ne porte ni moyen de paiement ni bénéficiaire :
 * Odoo les impose, et les accepter ici ferait croire au navigateur qu'il les
 * décide.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { demandeWave, fetchShipmentPayments, recordWavePayment } from '@/lib/ops/wave-payments';
import { logger, newCorrelationId } from '@/lib/logger';
import { reponseMutation } from '@/lib/ops/mutation-http';

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
    const data = await fetchShipmentPayments(
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
    logger.error('ops.wave.list.error', { correlationId, code });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}

export async function POST(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  return reponseMutation({
    request,
    correlationId,
    origineAcceptable,
    lireSession: readOpsSession,
    schema: demandeWave,
    evenement: 'ops.wave.payment.record',
    executer: (demande, sessionId) => recordWavePayment(
      decodeURIComponent(reference), demande, sessionId, correlationId),
  });
}
