/**
 * `POST /api/intakes/<reference>/late-lines` — ajouter un article arrivé après
 * la facture.
 *
 * Route distincte de `/lines`, parce que le geste l'est : celui-ci ne
 * s'applique qu'à un dossier déjà facturé et comptabilisé, et c'est Odoo qui
 * en juge. La passerelle ne relit ni `billing_locked` ni l'état de la facture
 * pour choisir — elle relaie, et le serveur refuse s'il y a lieu.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { addLateLine, demandeAjout } from '@/lib/ops/intake-lines';
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
    evenement: 'ops.intake.line.add_late',
    executer: (demande, sessionId) =>
      addLateLine(reference, demande, sessionId, correlationId),
  });
}
