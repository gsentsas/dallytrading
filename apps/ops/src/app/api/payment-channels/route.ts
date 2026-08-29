/** `GET /api/payment-channels` — les modes de paiement configurés. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchPaymentChannels } from '@/lib/ops/payments';
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
    const channels = await fetchPaymentChannels(session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: { channels } },
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
    logger.error('ops.payment.channels.error', { correlationId, code });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
