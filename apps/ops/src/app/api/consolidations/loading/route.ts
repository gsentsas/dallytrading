/**
 * `GET /api/consolidations/loading` — les départs que le quai peut préparer.
 *
 * Lecture seule et sans paramètre : la portée est décidée par le serveur, à
 * partir du rôle et de la société de l'opérateur. Aucun filtre n'est accepté,
 * pour qu'aucun écran ne puisse élargir sa vue en ajoutant une clé d'URL.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { logger, newCorrelationId } from '@/lib/logger';
import { fetchLoadings } from '@/lib/ops/loading';

export const dynamic = 'force-dynamic';

function reponse(corps: unknown, status: number) {
  return NextResponse.json(corps, {
    status, headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
}

export async function GET(request: Request): Promise<NextResponse> {
  if ([...new URL(request.url).searchParams.keys()].length > 0) {
    return reponse({ success: false, error: 'Filtre invalide.' }, 400);
  }
  const correlationId = newCorrelationId();
  const session = await readOpsSession();
  if (!session) return reponse({ success: false, error: 'Session expirée.' }, 401);
  try {
    const data = await fetchLoadings(session.odooSessionId, correlationId);
    return reponse({ success: true, data }, 200);
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    // La passerelle traduit déjà le 403 d'Odoo en `forbidden` : le code
    // métier `ops_forbidden` ne remonte jamais jusqu'ici.
    if (code === 'forbidden') {
      return reponse({ success: false, error: 'Session expirée.' }, 401);
    }
    logger.error('ops.loading.list.error', { correlationId, code });
    return reponse({ success: false, error: 'Service momentanément indisponible.' }, 503);
  }
}
