/** `POST /api/intakes/<reference>/lines` — ajouter un article. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { addLine, demandeAjout } from '@/lib/ops/intake-lines';
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
    schema: demandeAjout,
    evenement: 'ops.intake.line.add',
    executer: (demande, sessionId) =>
      addLine(reference, demande, sessionId, correlationId),
  });
}
