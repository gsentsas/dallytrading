/** `POST /api/expenses` — enregistrer une dépense engagée sur un départ. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { demandeDepense, recordExpense } from '@/lib/ops/expenses';
import { newCorrelationId } from '@/lib/logger';
import { reponseMutation } from '@/lib/ops/mutation-http';

export const dynamic = 'force-dynamic';

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  return reponseMutation({
    request,
    correlationId,
    origineAcceptable,
    lireSession: readOpsSession,
    schema: demandeDepense,
    evenement: 'ops.expense.record',
    // Le débit est celui des écritures de terrain, partagé avec les
    // réceptions : c'est un même opérateur, sur un même terminal, dont on
    // borne le rythme d'écriture — pas une file par type d'objet.
    executer: (demande, sessionId) => recordExpense(demande, sessionId, correlationId),
  });
}
