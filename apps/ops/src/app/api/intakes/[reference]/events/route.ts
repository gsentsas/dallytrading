/**
 * `GET|POST /api/intakes/<reference>/events` — les faits consignés d'un dossier.
 *
 * ## Pourquoi le POST emprunte le squelette commun
 *
 * C'est une mutation JSON portant un `request_uuid` : exactement ce que
 * `reponseMutation` sait faire. Réécrire ses cinq contrôles pour cette route
 * reviendrait à en oublier un — le débit avait déjà manqué une fois.
 *
 * Le budget, lui, est le sien : un opérateur qui documente un colis abîmé ne
 * doit pas consommer son droit d'en réceptionner un autre.
 *
 * ## Ce que cette route ne fait jamais
 *
 * Elle ne propose aucun moyen de publier au client, de notifier, ni de faire
 * avancer le dossier. Ces champs n'existent pas dans le schéma, et le schéma
 * est strict : les proposer fait tomber la demande au lieu de les ignorer.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { logger, newCorrelationId } from '@/lib/logger';
import { createEvent, demandeEvenement, fetchEvents } from '@/lib/ops/events';
import { reponseMutation } from '@/lib/ops/mutation-http';
import {
  OPS_EVENT_IP,
  OPS_EVENT_SESSION,
  cleEvenementIp,
  cleEvenementSession,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

const BUDGET_EVENEMENT = {
  session: OPS_EVENT_SESSION,
  ip: OPS_EVENT_IP,
  cleSession: cleEvenementSession,
  cleIp: cleEvenementIp,
} as const;

function erreur(status: number, message: string) {
  return NextResponse.json(
    { success: false, error: message },
    { status, headers: { 'Cache-Control': 'no-store' } },
  );
}

export async function GET(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');
  try {
    const data = await fetchEvents(
      decodeURIComponent(reference), session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found') return erreur(404, 'Dossier introuvable.');
    logger.error('ops.events.list.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
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
    schema: demandeEvenement,
    evenement: 'ops.events.recorded',
    budget: BUDGET_EVENEMENT,
    executer: (demande, sessionId) =>
      createEvent(
        decodeURIComponent(reference), demande, sessionId, correlationId),
  });
}
