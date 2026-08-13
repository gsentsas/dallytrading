/**
 * Gateway implementation over Odoo's legacy JSON-RPC.
 *
 * ## Status: not implemented — escape hatch only
 *
 * XML-RPC and JSON-RPC are deprecated in Odoo 19 and slated for removal. This
 * file exists so that *if* a legacy call ever becomes unavoidable, it lives here
 * and nowhere else. The specification is explicit on the point: legacy access
 * must be encapsulated in a single adapter, never scattered through the
 * application (§39).
 *
 * ## Why it is not implemented
 *
 * There is currently no need for it. `dally_api` covers the operations the site
 * performs, with better properties:
 *
 * | | `dally_api` | Legacy JSON-RPC |
 * |---|---|---|
 * | Surface | one endpoint per operation | any model, any method |
 * | Idempotency | unique DB constraint | none |
 * | Field exposure | explicit allowlist | whatever is read |
 * | Longevity | ours | scheduled for removal |
 *
 * The "any model, any method" row is the decisive one. Enabling legacy RPC means
 * granting the website's credential the ability to call arbitrary ORM methods,
 * which is exactly what §40 forbids. If this adapter is ever implemented, its
 * credential must be a dedicated Odoo user with minimal groups, and the
 * `/jsonrpc` route — currently blocked in the nginx configuration — must be
 * reopened deliberately.
 */

import type { OdooGateway } from './gateway';
import {
  OdooGatewayError,
  type LeadInput,
  type LeadRef,
  type PublicShipment,
  type QuoteInput,
  type QuoteRef,
  type ServiceType,
  type SourcingRequestInput,
  type SourcingRequestRef,
  type TradeOpportunityInput,
  type TradeOpportunityRef,
} from './types';

const NOT_IMPLEMENTED =
  'The legacy RPC adapter is not implemented. It exists only as a single, ' +
  'contained escape hatch (§39) and is not needed: use ODOO_GATEWAY_ADAPTER=dally_api. ' +
  'Enabling it also requires reopening /jsonrpc in the nginx configuration.';

export class LegacyRpcAdapter implements OdooGateway {
  async createLead(
    _input: LeadInput,
    _idempotencyKey: string,
    _correlationId: string,
  ): Promise<LeadRef> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }

  async createQuoteRequest(
    _input: QuoteInput,
    _idempotencyKey: string,
    _correlationId: string,
  ): Promise<QuoteRef> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }

  async createSourcingRequest(
    _input: SourcingRequestInput,
    _idempotencyKey: string,
    _correlationId: string,
  ): Promise<SourcingRequestRef> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }

  async createTradeOpportunity(
    _input: TradeOpportunityInput,
    _idempotencyKey: string,
    _correlationId: string,
  ): Promise<TradeOpportunityRef> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }

  async getShipmentByTracking(
    _reference: string,
    _token: string,
    _correlationId: string,
  ): Promise<PublicShipment | null> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }

  async listServiceTypes(
    _correlationId: string,
  ): Promise<ReadonlyArray<ServiceType>> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }

  async healthCheck(
    _correlationId: string,
  ): Promise<{ ok: boolean; database?: string }> {
    throw new OdooGatewayError('unavailable', NOT_IMPLEMENTED, 501);
  }
}
