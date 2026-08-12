/**
 * Gateway implementation over the `dally_api` Odoo module.
 *
 * This is the default. It talks to endpoints we own (`/api/v1/*`), which means the
 * contract is ours: it does not move when Odoo changes its RPC conventions, and
 * each endpoint exposes exactly one business operation instead of a generic
 * model-access surface (§40).
 */

import { getServerEnv } from '@/lib/env';
import { logger } from '@/lib/logger';
import type { OdooGateway } from './gateway';
import {
  OdooGatewayError,
  type LeadInput,
  type LeadRef,
  type OdooErrorCode,
  type PublicShipment,
  type ServiceType,
} from './types';

/** Envelope every dally_api endpoint returns. */
interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
  request_id?: string;
}

interface LeadResponse {
  reference: string;
  service: string | null;
  status: string;
}

/** Map Odoo's error codes onto the gateway's stable set. */
function mapErrorCode(status: number, apiCode?: string): OdooErrorCode {
  switch (apiCode) {
    case 'missing_api_key':
    case 'invalid_api_key':
      return 'unauthorized';
    case 'insufficient_scope':
      return 'forbidden';
    case 'rate_limit_exceeded':
      return 'rate_limited';
    default:
      break;
  }
  if (status === 401) return 'unauthorized';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 422 || status === 400) return 'validation_error';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'internal_error';
  return 'internal_error';
}

export class DallyApiAdapter implements OdooGateway {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;

  constructor() {
    const env = getServerEnv();
    // Trailing slash removed once, so path concatenation cannot produce "//".
    this.baseUrl = env.ODOO_URL.replace(/\/+$/, '');
    this.apiKey = env.ODOO_API_KEY;
    this.timeoutMs = env.ODOO_TIMEOUT_MS;
  }

  /** Perform a request, normalising every failure into OdooGatewayError. */
  private async call<T>(
    path: string,
    init: { method: 'GET' | 'POST'; body?: unknown },
    correlationId: string,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;

    // An unbounded fetch would let a stalled Odoo hold a Next.js worker open
    // until the proxy gives up, turning one slow call into a queue of them.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const startedAt = Date.now();

    try {
      const response = await fetch(url, {
        method: init.method,
        headers: {
          'Content-Type': 'application/json',
          // The key stays server-side. It is never forwarded to the browser and
          // never appears in a log (the logger redacts this header name).
          'X-API-Key': this.apiKey,
          'X-Correlation-Id': correlationId,
        },
        ...(init.body === undefined
          ? {}
          : { body: JSON.stringify(init.body) }),
        // Always hit Odoo: these responses are per-customer and must not be
        // served from Next's data cache.
        cache: 'no-store',
        signal: controller.signal,
      });

      const durationMs = Date.now() - startedAt;
      const text = await response.text();

      let envelope: ApiEnvelope<T> | null = null;
      try {
        envelope = text ? (JSON.parse(text) as ApiEnvelope<T>) : null;
      } catch {
        // A non-JSON body from Odoo usually means the proxy answered instead
        // (502/504) — treat it as unavailable rather than crashing on parse.
        logger.error('Odoo returned a non-JSON response', {
          correlationId,
          path,
          status: response.status,
          durationMs,
        });
        throw new OdooGatewayError(
          'unavailable',
          'The ERP returned an unreadable response.',
          502,
        );
      }

      if (!response.ok || !envelope?.success) {
        const apiCode = envelope?.error?.code;
        const code = mapErrorCode(response.status, apiCode);

        logger.warn('Odoo call rejected', {
          correlationId,
          path,
          status: response.status,
          apiCode,
          odooRequestId: envelope?.request_id,
          durationMs,
        });

        throw new OdooGatewayError(
          code,
          envelope?.error?.message ?? 'The ERP rejected the request.',
          response.status,
          envelope?.request_id,
        );
      }

      logger.info('Odoo call succeeded', {
        correlationId,
        path,
        status: response.status,
        odooRequestId: envelope.request_id,
        durationMs,
      });

      if (envelope.data === undefined) {
        throw new OdooGatewayError(
          'internal_error',
          'The ERP returned an empty payload.',
          502,
        );
      }
      return envelope.data;
    } catch (error) {
      if (error instanceof OdooGatewayError) {
        throw error;
      }
      // AbortError from our own timeout, or a DNS/connection failure.
      const isTimeout = error instanceof Error && error.name === 'AbortError';
      logger.error(isTimeout ? 'Odoo call timed out' : 'Odoo unreachable', {
        correlationId,
        path,
        timeoutMs: this.timeoutMs,
        durationMs: Date.now() - startedAt,
        error: error instanceof Error ? error.message : String(error),
      });
      throw new OdooGatewayError(
        isTimeout ? 'timeout' : 'unavailable',
        isTimeout
          ? 'The ERP did not respond in time.'
          : 'The ERP is unreachable.',
        504,
      );
    } finally {
      clearTimeout(timer);
    }
  }

  async createLead(
    input: LeadInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<LeadRef> {
    // Field names are converted here, once. Nothing outside this adapter needs
    // to know Odoo's snake_case payload shape.
    const payload = {
      request_uuid: idempotencyKey,
      service_code: input.serviceCode,
      first_name: input.firstName ?? '',
      last_name: input.lastName,
      company_name: input.companyName ?? '',
      email: input.email ?? '',
      phone: input.phone ?? '',
      whatsapp: input.whatsapp ?? '',
      city: input.city ?? '',
      country_code: input.countryCode ?? '',
      message: input.message ?? '',
      source_url: input.sourceUrl ?? '',
      utm_source: input.utmSource ?? '',
      utm_medium: input.utmMedium ?? '',
      utm_campaign: input.utmCampaign ?? '',
    };

    const data = await this.call<LeadResponse>(
      '/api/v1/leads',
      { method: 'POST', body: payload },
      correlationId,
    );

    return {
      reference: data.reference,
      serviceCode: data.service,
      status: 'received',
    };
  }

  async getShipmentByTracking(
    _reference: string,
    _correlationId: string,
  ): Promise<PublicShipment | null> {
    // Phase 7 endpoint. Declared so the interface is fully implemented and the
    // gap is an explicit, typed failure rather than a silent undefined.
    throw new OdooGatewayError(
      'unavailable',
      'Shipment tracking is not available yet (phase 7).',
      501,
    );
  }

  async listServiceTypes(
    _correlationId: string,
  ): Promise<ReadonlyArray<ServiceType>> {
    throw new OdooGatewayError(
      'unavailable',
      'The service catalogue endpoint is not available yet (phase 6).',
      501,
    );
  }

  async healthCheck(
    correlationId: string,
  ): Promise<{ ok: boolean; database?: string }> {
    const data = await this.call<{ status: string; database: string }>(
      '/api/v1/health',
      { method: 'GET' },
      correlationId,
    );
    return { ok: data.status === 'ok', database: data.database };
  }
}
