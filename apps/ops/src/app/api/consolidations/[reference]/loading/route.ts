/**
 * `GET|POST /api/consolidations/<reference>/loading` — préparer un départ.
 *
 * ## Pourquoi pas de `decodeURIComponent`
 *
 * App Router livre le segment déjà décodé. Le redécoder ferait passer
 * `A%252DB` pour `A-B` — une référence forgée atteindrait alors Odoo — et une
 * séquence `%` invalide lèverait un `URIError` hors du filet, rendu en 500.
 *
 * ## Ce que cette route ne fait jamais
 *
 * Elle ne clôt aucune collecte, ne met aucun départ « prêt », n'enregistre
 * aucun départ. Le schéma ne nomme que `load` et `unload`, et il est strict :
 * proposer autre chose fait tomber la demande au lieu de l'ignorer.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  applyLoading, demandeChargement, fetchLoading, normaliserReferenceDepart,
} from '@/lib/ops/loading';
import { reponseMutation } from '@/lib/ops/mutation-http';
import {
  OPS_LOADING_IP,
  OPS_LOADING_SESSION,
  cleChargementDemande,
  cleChargementIp,
  cleChargementSession,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

const BUDGET_CHARGEMENT = {
  session: OPS_LOADING_SESSION,
  ip: OPS_LOADING_IP,
  cleSession: cleChargementSession,
  cleIp: cleChargementIp,
  cleDemande: cleChargementDemande,
} as const;

function erreur(status: number, message: string) {
  return NextResponse.json(
    { success: false, error: message },
    { status, headers: { 'Cache-Control': 'private, no-store, max-age=0' } },
  );
}

export async function GET(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const propre = normaliserReferenceDepart(reference);
  if (propre === null) return erreur(400, 'Référence de départ invalide.');

  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');
  try {
    const data = await fetchLoading(propre, session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data },
      { status: 200, headers: { 'Cache-Control': 'private, no-store, max-age=0' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    // La passerelle normalise par statut HTTP : un 403 devient
    // `forbidden`, un 404 `not_found`. Les codes métier d'Odoo
    // (`ops_forbidden`, `consolidation_not_found`) ne remontent pas.
    if (code === 'forbidden') {
      return erreur(401, 'Session expirée.');
    }
    if (code === 'not_found') {
      return erreur(404, 'Départ introuvable.');
    }
    logger.error('ops.loading.detail.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}

export async function POST(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const propre = normaliserReferenceDepart(reference);
  if (propre === null) return erreur(400, 'Référence de départ invalide.');

  return reponseMutation({
    request,
    correlationId,
    origineAcceptable,
    lireSession: readOpsSession,
    schema: demandeChargement,
    evenement: 'ops.loading.applied',
    budget: BUDGET_CHARGEMENT,
    executer: (demande, sessionId) =>
      applyLoading(propre, demande, sessionId, correlationId),
  });
}
