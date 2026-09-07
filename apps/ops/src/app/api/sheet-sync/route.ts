/**
 * `GET /api/sheet-sync` — l'état du transport Odoo → tableur.
 *
 * L'autre moitié de l'écran de synchronisation. La première — ce que
 * l'appareil doit encore au CRM — ne passe jamais par ici : elle vit dans
 * IndexedDB, dans le navigateur, et doit rester lisible sans réseau.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchEtatProjection } from '@/lib/ops/supervision';
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
    const etat = await fetchEtatProjection(session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: etat },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (erreur) {
    // Un opérateur sans droit de supervision reçoit un 403, pas une panne :
    // l'écran doit cacher la section, pas proposer « réessayer ».
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      return NextResponse.json(
        { success: false, error: 'Accès réservé au responsable.' },
        { status: 403, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.sheet_sync.error', {
      correlationId,
      code: erreur instanceof OpsGatewayError ? erreur.code : 'error',
    });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
