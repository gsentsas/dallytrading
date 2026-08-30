/** `POST /api/intakes/<reference>/payments` — enregistrer un encaissement. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { demandePaiement, recordPayment } from '@/lib/ops/payments';
import { newCorrelationId } from '@/lib/logger';
import { reponseMutation } from '@/lib/ops/mutation-http';

export const dynamic = 'force-dynamic';

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
    schema: demandePaiement,
    evenement: 'ops.payment.record',
    executer: (demande, sessionId) =>
      recordPayment(reference, demande, sessionId, correlationId),
  });
}
