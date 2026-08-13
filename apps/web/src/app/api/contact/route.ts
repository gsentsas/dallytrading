/**
 * POST /api/contact — the BFF endpoint the contact form submits to.
 *
 * Reuses the existing `createLead` gateway method, and therefore the existing
 * `/api/v1/leads` Odoo endpoint. No new ERP surface: a contact message is a lead,
 * which is exactly what that endpoint is for.
 *
 * The quote pipeline (`/api/quotes`, `dally.quote.request`) is untouched. A contact
 * message is not a quote request, and routing it through the quote endpoint would
 * mean either creating quote requests with no service or relaxing that endpoint's
 * validation — both worse than a second small route.
 *
 * Same protections as the quote route: two rate-limit tiers, server-side validation,
 * honeypot, no secret in the browser.
 */

import { NextResponse } from 'next/server';
import {
  contactFormSchema,
  isBotSubmission,
  toLeadInput,
} from '@/features/contact/contact-schema';
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

const MAX_BODY_BYTES = 128 * 1024;

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
    `contact:req:${clientIp}`, COARSE_LIMIT, RATE_WINDOW_MS,
  );
  if (!coarse.allowed) {
    logger.warn('Contact endpoint rate limited (request tier)', {
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
      'Votre message est trop volumineux.', correlationId);
  }

  let rawBody: unknown;
  try {
    rawBody = await request.json();
  } catch {
    return jsonError(400, 'invalid_json', 'Requête invalide.', correlationId);
  }

  const parsed = contactFormSchema.safeParse(rawBody);
  if (!parsed.success) {
    const fields: Record<string, string> = {};
    for (const issue of parsed.error.issues) {
      const field = issue.path.join('.') || 'form';
      fields[field] ??= issue.message;
    }
    logger.info('Contact rejected by validation', {
      correlationId, clientIp, fields: Object.keys(fields),
    });
    return jsonError(
      422, 'validation_error', 'Certains champs sont invalides.',
      correlationId, { fields },
    );
  }

  const data = parsed.data;

  // A filled honeypot gets a normal-looking success, so the bot has no signal to
  // adapt to, while nothing is written to the CRM.
  if (isBotSubmission(data)) {
    logger.warn('Honeypot triggered on contact — submission discarded', {
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

  const submit = checkRateLimit(
    `contact:submit:${clientIp}`, SUBMIT_LIMIT, RATE_WINDOW_MS,
  );
  if (!submit.allowed) {
    logger.warn('Contact rate limited (submit tier)', { correlationId, clientIp });
    return jsonError(
      429, 'rate_limited',
      'Trop de messages envoyés. Merci de patienter une minute avant de réessayer.',
      correlationId, {}, { 'Retry-After': String(submit.retryAfterSeconds) },
    );
  }

  try {
    const lead = await getOdooGateway().createLead(
      toLeadInput(data),
      data.requestUuid,
      correlationId,
    );

    logger.info('Contact message recorded', {
      correlationId, clientIp,
      reference: lead.reference, subject: data.subject,
    });

    return NextResponse.json(
      {
        success: true,
        data: { reference: lead.reference, status: lead.status },
        requestId: correlationId,
      },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (error instanceof OdooGatewayError) {
      if (error.code === 'validation_error') {
        logger.info('Odoo rejected the contact message', {
          correlationId, odooCode: error.code,
          odooRequestId: error.odooRequestId,
        });
        return jsonError(
          422, 'validation_error',
          'Votre message n’a pas pu être enregistré en l’état. Merci de vérifier les informations saisies.',
          correlationId,
        );
      }

      logger.error('Odoo call failed during contact submission', {
        correlationId, clientIp,
        odooCode: error.code, odooStatus: error.status,
        odooRequestId: error.odooRequestId,
      });
      return jsonError(
        503, 'service_unavailable',
        'Nous ne parvenons pas à enregistrer votre message pour le moment. ' +
          'Merci de réessayer dans quelques minutes, ou de nous écrire sur WhatsApp.',
        correlationId, {}, { 'Retry-After': '120' },
      );
    }

    logger.error('Unexpected failure during contact submission', {
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
