/**
 * POST /api/quotes — the BFF endpoint the quote form submits to.
 *
 * The only path between the browser and Odoo. The browser never holds the Odoo API
 * key and never learns the ERP's address (§2, §54).
 *
 * Sequence: rate limit → shape validation → honeypot → service requirements →
 * gateway → response.
 *
 * Service requirements are checked against the catalogue Odoo published, not
 * against a table in this file. Odoo re-checks them anyway; doing it here first
 * turns a 422 round trip into an immediate field-level message.
 */

import { NextResponse } from 'next/server';
import {
  isBotSubmission,
  quoteRequestSchema,
  toQuoteInput,
  validateServiceRequirements,
} from '@/features/quote/quote-schema';
import { checkRateLimit, getClientIp } from '@/lib/rate-limit';
import { logger, newCorrelationId } from '@/lib/logger';
import { getOdooGateway } from '@/services/odoo';
import { getServiceCatalogue } from '@/services/odoo/catalogue-cache';
import { OdooGatewayError } from '@/services/odoo/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Two tiers, as on /api/leads: the coarse one bounds work an IP can cause,
 * including failed validation; the strict one applies only to submissions about to
 * create a record. A customer mistyping their e-mail three times in a multi-step
 * form must not be locked out.
 */
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
    {
      success: false,
      error: { code, message, ...extra },
      requestId: correlationId,
    },
    { status, headers: { 'Cache-Control': 'no-store', ...headers } },
  );
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const clientIp = getClientIp(request.headers);

  const coarse = checkRateLimit(
    `quotes:req:${clientIp}`, COARSE_LIMIT, RATE_WINDOW_MS,
  );
  if (!coarse.allowed) {
    logger.warn('Quote endpoint rate limited (request tier)', {
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

  // ─── Shape ──────────────────────────────────────────────────────
  const parsed = quoteRequestSchema.safeParse(rawBody);
  if (!parsed.success) {
    const fields: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const field = issue.path.join('.') || 'form';
      fields[field] ??= issue.message;
    }
    logger.info('Quote rejected by shape validation', {
      correlationId, clientIp, fields: Object.keys(fields),
    });
    return jsonError(
      422, 'validation_error', 'Certains champs sont invalides.',
      correlationId, { fields },
    );
  }

  const data = parsed.data;

  // ─── Honeypot ───────────────────────────────────────────────────
  // Answered with a normal-looking success so a bot gets no signal to adapt to,
  // while nothing is written to the CRM.
  if (isBotSubmission(data)) {
    logger.warn('Honeypot triggered on quote — submission discarded', {
      correlationId, clientIp,
    });
    return NextResponse.json(
      {
        success: true,
        data: { reference: 'DT-0000-000000', status: 'received' },
        requestId: correlationId,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  // ─── Service requirements, from Odoo's catalogue ────────────────
  try {
    const { services } = await getServiceCatalogue(correlationId);
    const service = services.find((entry) => entry.code === data.serviceCode);

    if (!service) {
      logger.info('Quote rejected: unknown service', {
        correlationId, serviceCode: data.serviceCode,
      });
      return jsonError(
        422, 'validation_error', 'Certains champs sont invalides.',
        correlationId,
        { fields: { serviceCode: 'Ce service n’est pas disponible.' } },
      );
    }

    const requirementErrors = validateServiceRequirements(data, service);
    if (Object.keys(requirementErrors).length > 0) {
      return jsonError(
        422, 'validation_error', 'Certains champs sont invalides.',
        correlationId, { fields: requirementErrors },
      );
    }
  } catch (error) {
    // The catalogue is unavailable and no cached copy is held. Odoo would reject
    // or accept the request anyway, so the submission is allowed through rather
    // than lost — Odoo remains the authority, and losing a real enquiry is worse
    // than accepting one whose service flags we could not pre-check.
    logger.warn('Could not pre-check service requirements; deferring to Odoo', {
      correlationId,
      error: error instanceof Error ? error.message : String(error),
    });
  }

  // ─── Submit tier ────────────────────────────────────────────────
  const submit = checkRateLimit(
    `quotes:submit:${clientIp}`, SUBMIT_LIMIT, RATE_WINDOW_MS,
  );
  if (!submit.allowed) {
    logger.warn('Quote rate limited (submit tier)', { correlationId, clientIp });
    return jsonError(
      429, 'rate_limited',
      'Trop de demandes envoyées. Merci de patienter une minute avant de réessayer.',
      correlationId, {}, { 'Retry-After': String(submit.retryAfterSeconds) },
    );
  }

  // ─── Odoo ───────────────────────────────────────────────────────
  try {
    const quote = await getOdooGateway().createQuoteRequest(
      toQuoteInput(data),
      data.requestUuid,
      correlationId,
    );

    logger.info('Quote request created', {
      correlationId, clientIp,
      reference: quote.reference, serviceCode: quote.serviceCode,
    });

    return NextResponse.json(
      {
        success: true,
        data: {
          reference: quote.reference,
          serviceCode: quote.serviceCode,
          status: quote.status,
        },
        requestId: correlationId,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (error instanceof OdooGatewayError) {
      if (error.code === 'validation_error') {
        logger.info('Odoo rejected the quote request', {
          correlationId, odooCode: error.code,
          odooRequestId: error.odooRequestId,
        });
        return jsonError(
          422, 'validation_error',
          'Votre demande n’a pas pu être enregistrée en l’état. Merci de vérifier les informations saisies.',
          correlationId,
        );
      }

      logger.error('Odoo call failed during quote creation', {
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

    logger.error('Unexpected failure during quote creation', {
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
