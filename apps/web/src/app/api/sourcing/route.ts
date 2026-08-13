/**
 * POST /api/sourcing — the BFF endpoint the sourcing form submits to.
 *
 * The only path between the browser and Odoo. The browser never holds the Odoo API key
 * and never learns the ERP's address (§33).
 *
 * Sequence: rate limit → validate → honeypot → submit tier → gateway → response.
 *
 * Same protections as the quote and contact routes, deliberately: three endpoints with
 * three different sets of guarantees is how one of them ends up unprotected.
 */

import { NextResponse } from 'next/server';
import {
  isBotSubmission,
  sourcingFormSchema,
  toSourcingInput,
} from '@/features/sourcing/sourcing-schema';
import { checkRateLimit, getClientIp } from '@/lib/rate-limit';
import { logger, newCorrelationId } from '@/lib/logger';
import { getOdooGateway } from '@/services/odoo';
import { OdooGatewayError } from '@/services/odoo/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Generous on requests, tight on submissions — see /api/quotes for the reasoning. */
const COARSE_LIMIT = 20;
const SUBMIT_LIMIT = 5;
const RATE_WINDOW_MS = 60_000;

const MAX_BODY_BYTES = 256 * 1024;

function jsonError(
  status: number,
  code: string,
  message: string,
  correlationId: string,
  extra: Record<string, unknown> = {},
  headers: Record<string, string> = {},
) {
  return NextResponse.json(
    { success: false, error: { code, message, ...extra }, requestId: correlationId },
    { status, headers: { 'Cache-Control': 'no-store', ...headers } },
  );
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const clientIp = getClientIp(request.headers);

  const coarse = checkRateLimit(
    `sourcing:req:${clientIp}`, COARSE_LIMIT, RATE_WINDOW_MS,
  );
  if (!coarse.allowed) {
    logger.warn('Sourcing endpoint rate limited (request tier)', {
      correlationId, clientIp,
    });
    return jsonError(
      429, 'rate_limited',
      'Trop de requêtes envoyées. Merci de patienter une minute avant de réessayer.',
      correlationId, {}, { 'Retry-After': String(coarse.retryAfterSeconds) },
    );
  }

  const contentLength = Number(request.headers.get('content-length') ?? '0');
  if (contentLength > MAX_BODY_BYTES) {
    return jsonError(413, 'payload_too_large',
      'La demande est trop volumineuse.', correlationId);
  }

  let rawBody: unknown;
  try {
    rawBody = await request.json();
  } catch {
    return jsonError(400, 'invalid_json', 'Requête invalide.', correlationId);
  }

  const parsed = sourcingFormSchema.safeParse(rawBody);
  if (!parsed.success) {
    const fields: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const field = issue.path.join('.') || 'form';
      fields[field] ??= issue.message;
    }
    logger.info('Sourcing request rejected by validation', {
      correlationId, clientIp, fields: Object.keys(fields),
    });
    return jsonError(
      422, 'validation_error', 'Certains champs sont invalides.',
      correlationId, { fields },
    );
  }

  const data = parsed.data;

  // A filled honeypot gets a normal-looking success, so the bot has no signal to adapt
  // to, while nothing is written to the ERP.
  if (isBotSubmission(data)) {
    logger.warn('Honeypot triggered on sourcing — submission discarded', {
      correlationId, clientIp,
    });
    return NextResponse.json(
      {
        success: true,
        data: { reference: 'DT-SRC-0000-000000', status: 'received' },
        requestId: correlationId,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  const submit = checkRateLimit(
    `sourcing:submit:${clientIp}`, SUBMIT_LIMIT, RATE_WINDOW_MS,
  );
  if (!submit.allowed) {
    logger.warn('Sourcing rate limited (submit tier)', { correlationId, clientIp });
    return jsonError(
      429, 'rate_limited',
      'Trop de demandes envoyées. Merci de patienter une minute avant de réessayer.',
      correlationId, {}, { 'Retry-After': String(submit.retryAfterSeconds) },
    );
  }

  try {
    const created = await getOdooGateway().createSourcingRequest(
      toSourcingInput(data),
      data.requestUuid,
      correlationId,
    );

    logger.info('Sourcing request created', {
      correlationId, clientIp, reference: created.reference,
    });

    return NextResponse.json(
      {
        success: true,
        data: { reference: created.reference, status: created.status },
        requestId: correlationId,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (error instanceof OdooGatewayError) {
      if (error.code === 'validation_error') {
        logger.info('Odoo rejected the sourcing request', {
          correlationId, odooCode: error.code,
          odooRequestId: error.odooRequestId,
        });
        return jsonError(
          422, 'validation_error',
          'Votre demande n’a pas pu être enregistrée en l’état. Merci de vérifier les informations saisies.',
          correlationId,
        );
      }

      logger.error('Odoo call failed during sourcing creation', {
        correlationId, clientIp,
        odooCode: error.code, odooStatus: error.status,
        odooRequestId: error.odooRequestId,
      });
      return jsonError(
        503, 'service_unavailable',
        'Nous ne parvenons pas à enregistrer votre demande pour le moment. ' +
          'Merci de réessayer dans quelques minutes ou de nous contacter par WhatsApp.',
        correlationId, {}, { 'Retry-After': '120' },
      );
    }

    logger.error('Unexpected failure during sourcing creation', {
      correlationId, clientIp,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
    });
    return jsonError(
      500, 'internal_error',
      `Une erreur interne est survenue. Référence : ${correlationId}`,
      correlationId,
    );
  }
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { success: false, error: { code: 'method_not_allowed', message: 'Use POST.' } },
    { status: 405, headers: { Allow: 'POST', 'Cache-Control': 'no-store' } },
  );
}
