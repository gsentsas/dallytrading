/**
 * `GET /api/anomalies` — ce qui demande une décision humaine.
 *
 * La liste est établie par Odoo. Le navigateur ne la reconstitue pas : savoir
 * qu'un colis n'est couvert par aucune facture demande de connaître ce qu'une
 * pièce comptabilisée couvre, et cette règle appartient à la facturation.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchAnomalies } from '@/lib/ops/supervision';
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
    const liste = await fetchAnomalies(session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: liste },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (erreur) {
    // Un logisticien reçoit un 403 : l'écran est une vue de supervision, et
    // le serveur l'a déjà refusée. Ce n'est pas une panne.
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      return NextResponse.json(
        { success: false, error: 'Accès réservé au responsable.' },
        { status: 403, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.anomalies.error', {
      correlationId,
      code: erreur instanceof OpsGatewayError ? erreur.code : 'error',
    });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
