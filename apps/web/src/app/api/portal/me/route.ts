/**
 * GET /api/portal/me
 *
 * Renvoie l'identité telle qu'Odoo la donne, ou 401. Le cookie n'est jamais
 * décodé pour en tirer un nom : il ne contient qu'un identifiant de session, et
 * c'est Odoo qui répond à la question « qui est-ce ».
 *
 * Le 401 couvre indistinctement : pas de cookie, cookie altéré, cookie expiré,
 * session Odoo révoquée, compte désactivé. L'appelant n'a rien à faire de la
 * distinction, et la fournir renseignerait sur l'état interne.
 */

import type { NextResponse } from 'next/server';

import { getPortalMe } from '@/lib/portal/auth';
import { PortalGatewayError } from '@/lib/portal/odoo-portal';
import { logger, newCorrelationId } from '@/lib/logger';
import { portalError, portalJson } from '../_shared';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  const correlationId = newCorrelationId();

  try {
    const identity = await getPortalMe(correlationId);
    if (!identity) {
      return portalError(401, 'unauthenticated', 'Session expirée.', correlationId);
    }
    return portalJson(identity);
  } catch (error) {
    const code = error instanceof PortalGatewayError ? error.code : 'unknown';
    logger.error('Portal me unavailable', { correlationId, code });
    // 503 et non 401 : dire « session expirée » quand Odoo est simplement
    // injoignable pousserait l'utilisateur à se reconnecter en boucle.
    return portalError(
      503, 'unavailable',
      'Le service est momentanément indisponible.',
      correlationId,
    );
  }
}
