/** `PUT /api/intakes/<reference>/lines/<lineUuid>` — corriger un article. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { demandeCorrection, updateLine } from '@/lib/ops/intake-lines';
import { newCorrelationId } from '@/lib/logger';
import { reponseMutation } from '@/lib/ops/mutation-http';

export const dynamic = 'force-dynamic';

export async function PUT(
  request: Request,
  contexte: { params: Promise<{ reference: string; lineUuid: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference, lineUuid } = await contexte.params;
  return reponseMutation({
    request,
    correlationId,
    origineAcceptable,
    lireSession: readOpsSession,
    schema: demandeCorrection,
    evenement: 'ops.intake.line.update',
    executer: (demande, sessionId) =>
      updateLine(reference, lineUuid, demande, sessionId, correlationId),
  });
}
