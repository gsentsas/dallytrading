/**
 * POST /api/portal/quotes/[reference]/decision
 *
 * Première transition de dossier depuis le portail. L'identité reste uniquement
 * dans le cookie HttpOnly : le navigateur ne fournit ni partenaire, ni client, ni
 * utilisateur, et cette route n'importe jamais la passerelle d'intégration.
 */

import type { NextResponse } from 'next/server';

import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import { decideQuote } from '@/lib/portal/business';
import { checkOrigin } from '@/lib/portal/csrf';
import {
  portalQuoteDecisionSchema,
  type PortalQuoteDecision,
} from '@/lib/portal/dto';
import { PortalGatewayError } from '@/lib/portal/odoo-portal';
import { portalError, portalJson } from '@/app/api/portal/_shared';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_BODY_BYTES = 4 * 1024;
const SAFE_REFERENCE = /^[A-Za-z0-9_.-]{1,128}$/;

function refused(
  requestId: string,
  reference: string,
  reason: string,
  decision?: PortalQuoteDecision['decision'],
) {
  logger.warn('Portal quote decision refused', {
    requestId,
    action: 'quote_decision',
    reference: SAFE_REFERENCE.test(reference) ? reference : 'invalid',
    ...(decision ? { decision } : {}),
    result: 'failure',
    reason,
  });
}

function invalidRequest(
  requestId: string,
  reference: string,
  reason: string,
): NextResponse {
  refused(requestId, reference, reason);
  return portalError(
    400, 'invalid_request', 'La décision transmise est invalide.', requestId,
  );
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const requestId = newCorrelationId();
  const { reference } = await params;

  const origin = checkOrigin(
    request.headers, getServerEnv().NEXT_PUBLIC_SITE_URL,
  );
  if (!origin.ok) {
    refused(requestId, reference, `origin_${origin.reason}`);
    return portalError(403, 'forbidden', 'Requête refusée.', requestId);
  }

  if (!SAFE_REFERENCE.test(reference)) {
    refused(requestId, reference, 'not_found');
    return portalError(404, 'not_found', 'Devis introuvable.', requestId);
  }

  if (Number(request.headers.get('content-length') ?? '0') > MAX_BODY_BYTES) {
    return invalidRequest(requestId, reference, 'body_too_large');
  }

  let body: string;
  let raw: unknown;
  try {
    body = await request.text();
  } catch {
    return invalidRequest(requestId, reference, 'unreadable_body');
  }
  if (new TextEncoder().encode(body).byteLength > MAX_BODY_BYTES) {
    return invalidRequest(requestId, reference, 'body_too_large');
  }
  try {
    raw = JSON.parse(body) as unknown;
  } catch {
    return invalidRequest(requestId, reference, 'invalid_json');
  }

  const parsed = portalQuoteDecisionSchema.safeParse(raw);
  if (!parsed.success) {
    return invalidRequest(requestId, reference, 'invalid_payload');
  }

  try {
    const quote = await decideQuote(reference, parsed.data, requestId);
    logger.info('Portal quote decision', {
      requestId,
      action: 'quote_decision',
      reference,
      decision: parsed.data.decision,
      result: 'success',
    });
    return portalJson(quote);
  } catch (error) {
    const code = error instanceof PortalGatewayError ? error.code : 'unavailable';
    const status =
      code === 'invalid_request' ? 400
        : code === 'unauthenticated' ? 401
          : code === 'forbidden' ? 403
            : code === 'not_found' ? 404
              : code === 'conflict' ? 409
                : 503;
    const message =
      status === 400 ? 'La décision transmise est invalide.'
        : status === 401 ? 'Session expirée.'
          : status === 403 ? 'Requête refusée.'
            : status === 404 ? 'Devis introuvable.'
              : status === 409 ? 'Ce devis ne peut plus recevoir cette décision.'
                : 'Le service est momentanément indisponible.';

    const details = {
      requestId,
      action: 'quote_decision',
      reference,
      decision: parsed.data.decision,
      result: 'failure',
      code,
    };
    if (status >= 500) logger.error('Portal quote decision', details);
    else logger.warn('Portal quote decision', details);
    return portalError(status, code, message, requestId);
  }
}
