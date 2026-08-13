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
  type QuoteInput,
  type QuoteRef,
  type ServiceType,
  type SourcingRequestInput,
  type SourcingRequestRef,
  type TradeOperationType,
  type TradeOpportunityInput,
  type TradeOpportunityRef,
} from './types';

/** Envelope every dally_api endpoint returns. */
interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
  request_id?: string;
}

interface TradeResponse {
  readonly reference: string;
  readonly operationType: TradeOperationType;
}

interface LeadResponse {
  reference: string;
  service: string | null;
  status: string;
}

/** Shape returned by GET /api/v1/services. */
interface ServicesResponse {
  services: ReadonlyArray<{
    code: string;
    name: string;
    description: string;
    active: boolean;
    sort_order: number;
    requires_origin: boolean;
    requires_destination: boolean;
    requires_weight: boolean;
    requires_volume: boolean;
    requires_vehicle: boolean;
    requires_budget: boolean;
    requires_goods: boolean;
  }>;
}

/** Shape returned by GET /api/v1/tracking/<reference>. */
interface TrackingResponse {
  reference: string;
  transportMode: string;
  transportModeLabel: string;
  origin: string | null;
  destination: string | null;
  status: string;
  statusLabel: string;
  departureDate: string | null;
  estimatedArrival: string | null;
  actualArrival: string | null;
  lastUpdate: string | null;
  carrierTrackingNumber: string | null;
  containerNumber: string | null;
  goodsDescription: string | null;
  packagesCount: number;
  timeline?: ReadonlyArray<{
    date: string;
    status: string;
    statusLabel: string;
    location: string | null;
    description: string | null;
  }>;
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

/**
 * Which Odoo integration identity a call should use.
 *
 * Not a convenience: an Odoo API key is bound to one acting user, and that user's
 * groups are what actually bound the call. Sending every request with one key
 * would mean one identity for every capability — the opposite of ADR-011.
 */
type Capability = 'default' | 'sourcing' | 'trade' | 'tracking';

export class DallyApiAdapter implements OdooGateway {
  private readonly baseUrl: string;
  private readonly keys: Readonly<Record<Capability, string>>;
  private readonly timeoutMs: number;

  constructor() {
    const env = getServerEnv();
    // Trailing slash removed once, so path concatenation cannot produce "//".
    this.baseUrl = env.ODOO_URL.replace(/\/+$/, '');
    this.timeoutMs = env.ODOO_TIMEOUT_MS;
    // Each capability falls back to the default key. An instance that has not
    // split its keys keeps working and fails with an explicit 403 from Odoo,
    // rather than the call silently running as a wider identity.
    this.keys = {
      default: env.ODOO_API_KEY,
      sourcing: env.ODOO_API_KEY_SOURCING ?? env.ODOO_API_KEY,
      trade: env.ODOO_API_KEY_TRADE ?? env.ODOO_API_KEY,
      tracking: env.ODOO_API_KEY_TRACKING ?? env.ODOO_API_KEY,
    };
  }

  /** Perform a request, normalising every failure into OdooGatewayError. */
  private async call<T>(
    path: string,
    init: { method: 'GET' | 'POST'; body?: unknown },
    correlationId: string,
    capability: Capability = 'default',
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
          'X-API-Key': this.keys[capability],
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

  async createSourcingRequest(
    input: SourcingRequestInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<SourcingRequestRef> {
    // Nested to match the API contract, and camelCase to snake_case happens here,
    // once. Nothing outside this adapter knows the wire format.
    const payload: Record<string, unknown> = {
      request_uuid: idempotencyKey,
      service_code: input.serviceCode ?? 'sourcing',
      customer: {
        first_name: input.customer.firstName ?? '',
        last_name: input.customer.lastName,
        company: input.customer.company ?? '',
        email: input.customer.email ?? '',
        phone: input.customer.phone ?? '',
        whatsapp: input.customer.whatsapp ?? '',
      },
      product: {
        name: input.product.name,
        description: input.product.description ?? '',
        specifications: input.product.specifications ?? '',
        reference: input.product.reference ?? '',
        url: input.product.url ?? '',
      },
      quantity: input.quantity,
      uom: input.uom ?? '',
      currency: input.currency ?? '',
      preferred_origin_country: input.preferredOriginCountry ?? '',
      destination_country: input.destinationCountry ?? '',
      requested_deadline: input.requestedDeadline ?? '',
      required_delivery_date: input.requiredDeliveryDate ?? '',
      notes: input.notes ?? '',
      source_url: input.sourceUrl ?? '',
      referrer_url: input.referrerUrl ?? '',
    };

    // Numbers are omitted rather than sent as 0 when absent: a zero budget is a
    // statement, an absent one is "not decided yet", and a salesperson needs to tell
    // them apart.
    if (input.budget !== undefined) payload.budget = input.budget;
    if (input.targetUnitPrice !== undefined) {
      payload.target_unit_price = input.targetUnitPrice;
    }
    if (input.utm) {
      payload.utm = {
        source: input.utm.source ?? '',
        medium: input.utm.medium ?? '',
        campaign: input.utm.campaign ?? '',
      };
    }

    const data = await this.call<LeadResponse>(
      '/api/v1/sourcing/requests',
      { method: 'POST', body: payload },
      correlationId,
      'sourcing',
    );

    return {
      reference: data.reference,
      serviceCode: data.service,
      status: 'received',
    };
  }

  async createTradeOpportunity(
    input: TradeOpportunityInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<TradeOpportunityRef> {
    // camelCase to snake_case happens here, once. Nothing outside this adapter knows
    // the wire format — which is the whole reason the gateway exists.
    //
    // Note what this payload cannot carry: there is no key for a cost, a margin, a
    // supplier or a commission, because the input type has no such field. The leak
    // is prevented at compile time, not filtered at runtime.
    const payload: Record<string, unknown> = {
      request_uuid: idempotencyKey,
      operation_type: input.operationType,
      subject: input.subject,
      description: input.description ?? '',
      requirements: input.requirements ?? '',
      service_code: input.serviceCode ?? '',
      contact: {
        name: input.contact.name,
        company: input.contact.company ?? '',
        email: input.contact.email ?? '',
        phone: input.contact.phone ?? '',
        whatsapp: input.contact.whatsapp ?? '',
        country: input.contact.country ?? '',
      },
      origin_country: input.originCountry ?? '',
      destination_country: input.destinationCountry ?? '',
      source_url: input.sourceUrl ?? '',
      referrer_url: input.referrerUrl ?? '',
    };

    const data = await this.call<TradeResponse>(
      '/api/v1/trade/opportunities',
      { method: 'POST', body: payload },
      correlationId,
      'trade',
    );

    return {
      reference: data.reference,
      // Echoed from the server rather than from the input: the server is the
      // authority on what was actually recorded.
      operationType: data.operationType,
      status: 'received',
    };
  }

  async getShipmentByTracking(
    reference: string,
    token: string,
    correlationId: string,
  ): Promise<PublicShipment | null> {
    // Normalised here as well as in Odoo, so a reference pasted with a
    // non-breaking space does not become a pointless round trip.
    const normalised = reference.replace(/\s+/g, '').toUpperCase();
    // No token means no lookup: the reference alone is never sufficient, and
    // sending a tokenless request would only produce a 404 round trip.
    if (!normalised || !token) {
      return null;
    }

    try {
      const data = await this.call<TrackingResponse>(
        `/api/v1/tracking/${encodeURIComponent(normalised)}` +
          `?token=${encodeURIComponent(token)}`,
        { method: 'GET' },
        correlationId,
        'tracking',
      );

      return {
        reference: data.reference,
        transportMode: data.transportMode,
        transportModeLabel: data.transportModeLabel,
        origin: data.origin,
        destination: data.destination,
        status: data.status,
        statusLabel: data.statusLabel,
        departureDate: data.departureDate,
        estimatedArrival: data.estimatedArrival,
        actualArrival: data.actualArrival,
        lastUpdate: data.lastUpdate,
        carrierTrackingNumber: data.carrierTrackingNumber,
        containerNumber: data.containerNumber,
        goodsDescription: data.goodsDescription,
        packagesCount: data.packagesCount,
        timeline: data.timeline ?? [],
      };
    } catch (error) {
      // An unknown reference is a normal outcome of a customer typing one in, not
      // an error condition. Returning null keeps the page from treating "not
      // found" as a failure — and keeps "unknown" indistinguishable from
      // "exists but not yours", so the endpoint cannot be used to enumerate.
      if (error instanceof OdooGatewayError && error.code === 'not_found') {
        return null;
      }
      throw error;
    }
  }

  async listServiceTypes(
    correlationId: string,
  ): Promise<ReadonlyArray<ServiceType>> {
    const data = await this.call<ServicesResponse>(
      '/api/v1/services',
      { method: 'GET' },
      correlationId,
    );

    // Sorted here rather than trusting the wire order: the contract publishes
    // sort_order precisely so display order is Odoo's decision, and relying on
    // array order would make it depend on the serialiser instead.
    return [...(data.services ?? [])]
      .map((service) => ({
        code: service.code,
        name: service.name,
        description: service.description ?? '',
        active: Boolean(service.active),
        sort_order: service.sort_order ?? 0,
        requires_origin: Boolean(service.requires_origin),
        requires_destination: Boolean(service.requires_destination),
        requires_weight: Boolean(service.requires_weight),
        requires_volume: Boolean(service.requires_volume),
        requires_vehicle: Boolean(service.requires_vehicle),
        requires_budget: Boolean(service.requires_budget),
        requires_goods: Boolean(service.requires_goods),
      }))
      .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name));
  }

  async createQuoteRequest(
    input: QuoteInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<QuoteRef> {
    // camelCase to snake_case happens here, once. Nothing outside this adapter
    // needs to know the wire format.
    const payload: Record<string, unknown> = {
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
      origin_country_code: input.originCountryCode ?? '',
      origin_city: input.originCity ?? '',
      destination_country_code: input.destinationCountryCode ?? '',
      destination_city: input.destinationCity ?? '',
      goods_description: input.goodsDescription ?? '',
      quantity: input.quantity ?? '',
      vehicle_make: input.vehicleMake ?? '',
      vehicle_model: input.vehicleModel ?? '',
      vehicle_year: input.vehicleYear ?? '',
      budget: input.budget ?? '',
      message: input.message ?? '',
      source_url: input.sourceUrl ?? '',
      referrer_url: input.referrerUrl ?? '',
      utm_source: input.utmSource ?? '',
      utm_medium: input.utmMedium ?? '',
      utm_campaign: input.utmCampaign ?? '',
    };

    // Numbers are omitted rather than sent as 0 when absent: a zero weight is a
    // statement ("it weighs nothing"), an absent one is an admission ("not known
    // yet"), and an operator needs to tell them apart.
    if (input.weightKg !== undefined) payload.weight_kg = input.weightKg;
    if (input.volumeCbm !== undefined) payload.volume_cbm = input.volumeCbm;
    if (input.packagesCount !== undefined) {
      payload.packages_count = input.packagesCount;
    }

    const data = await this.call<LeadResponse>(
      '/api/v1/quotes',
      { method: 'POST', body: payload },
      correlationId,
    );

    return {
      reference: data.reference,
      serviceCode: data.service,
      status: 'received',
    };
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
