/**
 * POST /api/leads — the BFF endpoint the quote form submits to.
 *
 * This is the only path between the browser and Odoo. The browser never holds the
 * Odoo API key and never learns the ERP's address (§2, §54): it talks to this
 * same-origin route, which authenticates to Odoo server-side.
 *
 * Sequence: rate limit → validate → honeypot → gateway → response.
 */

import { NextResponse } from 'next/server';
import { quoteFormSchema, isBotSubmission, toLeadInput } from '@/features/quote/schema';
import { checkRateLimit, getClientIp } from '@/lib/rate-limit';
import { logger, newCorrelationId } from '@/lib/logger';
import { getOdooGateway } from '@/services/odoo';
import { OdooGatewayError } from '@/services/odoo/types';

/** Node runtime: the gateway uses server-only configuration and fetch timeouts. */
export const runtime = 'nodejs';

/** Never statically optimised — every call must reach Odoo. */
export const dynamic = 'force-dynamic';

/**
 * Two rate-limit tiers, because they defend against different things.
 *
 * The coarse tier bounds how much work an IP can make this process do, including
 * requests that fail validation. It is generous: a customer filling a multi-step
 * form and mistyping their email three times must not be locked out — that would
 * punish exactly the users we want.
 *
 * The strict tier applies only to submissions that passed validation and are
 * about to create a lead. That is the expensive, write-side operation, and the
 * one worth limiting tightly.
 */
const COARSE_LIMIT = 20;
const SUBMIT_LIMIT = 5;
const RATE_WINDOW_MS = 60_000;

/** Largest body accepted, mirroring the cap in nginx and in dally_api. */
const MAX_BODY_BYTES = 256 * 1024;

function jsonError(
  status: number,
  code: string,
  message: string,
  correlationId: string,
  extraHeaders: Record<string, string> = {},
) {
  return NextResponse.json(
    { success: false, error: { code, message }, requestId: correlationId },
    {
      status,
      headers: { 'Cache-Control': 'no-store', ...extraHeaders },
    },
  );
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const clientIp = getClientIp(request.headers);

  // ─── Rate limit, tier 1: total requests ─────────────────────────
  const coarse = checkRateLimit(
    `leads:req:${clientIp}`,
    COARSE_LIMIT,
    RATE_WINDOW_MS,
  );
  if (!coarse.allowed) {
    logger.warn('Lead endpoint rate limited (request tier)', {
      correlationId,
      clientIp,
    });
    return jsonError(
      429,
      'rate_limited',
      'Trop de requêtes envoyées. Merci de patienter une minute avant de réessayer.',
      correlationId,
      { 'Retry-After': String(coarse.retryAfterSeconds) },
    );
  }

  // ─── Body ───────────────────────────────────────────────────────
  const contentLength = Number(request.headers.get('content-length') ?? '0');
  if (contentLength > MAX_BODY_BYTES) {
    return jsonError(
      413,
      'payload_too_large',
      'La demande est trop volumineuse.',
      correlationId,
    );
  }

  let rawBody: unknown;
  try {
    rawBody = await request.json();
  } catch {
    return jsonError(
      400,
      'invalid_json',
      'Requête invalide.',
      correlationId,
    );
  }

  // ─── Validation ─────────────────────────────────────────────────
  // Server-side and authoritative: this route is reachable without the browser.
  const parsed = quoteFormSchema.safeParse(rawBody);
  if (!parsed.success) {
    // Field-level messages so the form can highlight the offending inputs.
    const fieldErrors: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const field = issue.path.join('.') || 'form';
      fieldErrors[field] ??= issue.message;
    }

    logger.info('Lead submission rejected by validation', {
      correlationId,
      clientIp,
      fields: Object.keys(fieldErrors),
    });

    return NextResponse.json(
      {
        success: false,
        error: {
          code: 'validation_error',
          message: 'Certains champs sont invalides.',
          fields: fieldErrors,
        },
        requestId: correlationId,
      },
      { status: 422, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  const data = parsed.data;

  // ─── Honeypot ───────────────────────────────────────────────────
  // A filled hidden field means an automated submission. It is answered with a
  // normal-looking success so the bot has no signal to adapt to, while nothing is
  // written to the CRM.
  if (isBotSubmission(data)) {
    logger.warn('Honeypot triggered — submission discarded', {
      correlationId,
      clientIp,
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

  // ─── Rate limit, tier 2: actual submissions ─────────────────────
  // Applied only now, so a valid submission is what consumes this budget —
  // never a typo the customer already corrected.
  const submit = checkRateLimit(
    `leads:submit:${clientIp}`,
    SUBMIT_LIMIT,
    RATE_WINDOW_MS,
  );
  if (!submit.allowed) {
    logger.warn('Lead submission rate limited (submit tier)', {
      correlationId,
      clientIp,
    });
    return jsonError(
      429,
      'rate_limited',
      'Trop de demandes envoyées. Merci de patienter une minute avant de réessayer.',
      correlationId,
      { 'Retry-After': String(submit.retryAfterSeconds) },
    );
  }

  // ─── Odoo ───────────────────────────────────────────────────────
  try {
    const gateway = getOdooGateway();
    const lead = await gateway.createLead(
      toLeadInput(data),
      data.requestUuid,
      correlationId,
    );

    logger.info('Lead created', {
      correlationId,
      clientIp,
      reference: lead.reference,
      serviceCode: lead.serviceCode,
    });

    return NextResponse.json(
      {
        success: true,
        data: {
          reference: lead.reference,
          serviceCode: lead.serviceCode,
          status: lead.status,
        },
        requestId: correlationId,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (error instanceof OdooGatewayError) {
      // Business rejections are worth showing; infrastructure failures are not.
      // A customer must never read "ERP unreachable" — they get an actionable
      // message and a reference support can trace.
      if (error.code === 'validation_error') {
        logger.info('Odoo rejected the lead', {
          correlationId,
          odooCode: error.code,
          odooRequestId: error.odooRequestId,
        });
        return jsonError(
          422,
          'validation_error',
          'Votre demande n’a pas pu être enregistrée en l’état. Merci de vérifier les informations saisies.',
          correlationId,
        );
      }

      logger.error('Odoo call failed during lead creation', {
        correlationId,
        clientIp,
        odooCode: error.code,
        odooStatus: error.status,
        odooRequestId: error.odooRequestId,
      });

      return jsonError(
        503,
        'service_unavailable',
        'Nous ne parvenons pas à enregistrer votre demande pour le moment. ' +
          'Merci de réessayer dans quelques minutes ou de nous contacter par WhatsApp.',
        correlationId,
        { 'Retry-After': '120' },
      );
    }

    // Unexpected: log the whole thing server-side, reveal nothing.
    logger.error('Unexpected failure during lead creation', {
      correlationId,
      clientIp,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
    });

    return jsonError(
      500,
      'internal_error',
      `Une erreur interne est survenue. Référence : ${correlationId}`,
      correlationId,
    );
  }
}

/** Explicit 405 rather than Next's default, so the contract is unambiguous. */
export async function GET(): Promise<NextResponse> {
  return NextResponse.json(
    { success: false, error: { code: 'method_not_allowed', message: 'Use POST.' } },
    { status: 405, headers: { Allow: 'POST', 'Cache-Control': 'no-store' } },
  );
}
