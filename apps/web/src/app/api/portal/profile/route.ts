/**
 * PATCH /api/portal/profile
 *
 * Première mutation métier du portail. Le navigateur ne choisit aucune identité :
 * le BFF ouvre son cookie HttpOnly, transmet uniquement la session Odoo réelle et
 * Odoo dérive le contact de request.env.user.
 */

import type { NextResponse } from 'next/server';

import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import { updateProfile } from '@/lib/portal/business';
import { checkOrigin } from '@/lib/portal/csrf';
import { portalProfileUpdateSchema } from '@/lib/portal/dto';
import { PortalGatewayError } from '@/lib/portal/odoo-portal';
import { portalError, portalJson } from '../_shared';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_BODY_BYTES = 8 * 1024;

function invalidRequest(requestId: string, reason: string): NextResponse {
  logger.warn('Portal profile update refused', {
    requestId, action: 'profile_update', result: 'failure', reason,
  });
  return portalError(
    400, 'invalid_request', 'Les informations transmises sont invalides.', requestId,
  );
}

export async function PATCH(request: Request): Promise<NextResponse> {
  const requestId = newCorrelationId();

  const origin = checkOrigin(
    request.headers, getServerEnv().NEXT_PUBLIC_SITE_URL,
  );
  if (!origin.ok) {
    logger.warn('Portal profile update refused', {
      requestId, action: 'profile_update', result: 'failure', reason: origin.reason,
    });
    return portalError(403, 'forbidden', 'Requête refusée.', requestId);
  }

  if (Number(request.headers.get('content-length') ?? '0') > MAX_BODY_BYTES) {
    return invalidRequest(requestId, 'body_too_large');
  }

  let body: string;
  let raw: unknown;
  try {
    body = await request.text();
  } catch {
    return invalidRequest(requestId, 'unreadable_body');
  }
  if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) {
    return invalidRequest(requestId, 'body_too_large');
  }
  try {
    raw = JSON.parse(body) as unknown;
  } catch {
    return invalidRequest(requestId, 'invalid_json');
  }

  const parsed = portalProfileUpdateSchema.safeParse(raw);
  if (!parsed.success) {
    return invalidRequest(requestId, 'invalid_payload');
  }

  try {
    const profile = await updateProfile(parsed.data, requestId);
    logger.info('Portal profile update', {
      requestId, action: 'profile_update', result: 'success',
    });
    return portalJson(profile);
  } catch (error) {
    const code = error instanceof PortalGatewayError ? error.code : 'unavailable';
    const status =
      code === 'invalid_request' ? 400
        : code === 'unauthenticated' ? 401
          : code === 'forbidden' ? 403
            : 503;
    const message =
      status === 400 ? 'Les informations transmises sont invalides.'
        : status === 401 ? 'Session expirée.'
          : status === 403 ? 'Requête refusée.'
            : 'Le service est momentanément indisponible.';

    const level = status >= 500 ? 'error' : 'warn';
    logger[level]('Portal profile update', {
      requestId, action: 'profile_update', result: 'failure', code,
    });
    return portalError(status, code, message, requestId);
  }
}
