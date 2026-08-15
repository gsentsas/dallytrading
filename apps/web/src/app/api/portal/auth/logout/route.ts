/**
 * POST /api/portal/auth/logout
 *
 * Deux gestes, dans cet ordre : détruire la session côté Odoo, puis retirer le
 * cookie. L'ordre compte — retirer d'abord le cookie perdrait l'identifiant
 * nécessaire pour fermer la session Odoo, qui resterait alors valide jusqu'à
 * expiration, réutilisable par quiconque l'aurait interceptée.
 *
 * POST et non GET : une déconnexion modifie l'état, et un `<img src="/logout">`
 * sur un site tiers déconnecterait les visiteurs.
 *
 * Toujours 200. Une déconnexion qui échoue laisserait l'utilisateur avec un
 * cookie qu'il ne peut plus retirer — c'est le seul cas où l'échec est pire que
 * le succès partiel.
 */

import type { NextResponse } from 'next/server';

import { clearPortalSession, logoutPortal } from '@/lib/portal/auth';
import { checkOrigin } from '@/lib/portal/csrf';
import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import { portalError, portalJson } from '../../_shared';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();

  const origin = checkOrigin(request.headers, getServerEnv().NEXT_PUBLIC_SITE_URL);
  if (!origin.ok) {
    return portalError(403, 'forbidden', 'Requête refusée.', correlationId);
  }

  try {
    await logoutPortal(correlationId);
  } catch {
    // Odoo injoignable : le cookie part quand même. Le laisser en place au motif
    // qu'Odoo n'a pas répondu maintiendrait une session ouverte sur un poste que
    // l'utilisateur croit avoir quitté.
    await clearPortalSession();
  }

  logger.info('Portal logout', { correlationId });
  return portalJson({ loggedOut: true });
}
