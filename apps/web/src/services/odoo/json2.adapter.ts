/**
 * Gateway implementation over Odoo 19's External JSON-2 API.
 *
 * ## Status: not implemented — deliberately
 *
 * The strategy (ADR-008) is to prefer JSON-2 once it is confirmed available and
 * appropriate for this deployment. That confirmation has **not** been done: the
 * project has no running Odoo 19 instance yet, so JSON-2's availability rests on
 * documentation alone.
 *
 * Writing a plausible-looking implementation against an unverified API would be
 * worse than leaving it unimplemented: it would look finished, pass review, and
 * fail in production. So this class throws a clear error, and switching to it is
 * a one-line change in `.env` once phase 3 has validated the protocol.
 *
 * ## What phase 3 must establish before this is written
 *
 * 1. Whether JSON-2 is reachable on a self-hosted Odoo 19 Community install.
 * 2. How it authenticates (API key vs. session) and whether a key can be scoped
 *    to specific models — a key that can read any model would be a step
 *    backwards from `dally_api`, which exposes one operation per endpoint (§40).
 * 3. Whether idempotency can be enforced (§41). `dally_api` guarantees it with a
 *    unique database constraint. A generic API without that guarantee cannot be
 *    used for lead creation, whatever else it offers.
 * 4. Whether responses can be restricted to an explicit field allowlist, so the
 *    public tracking page cannot leak margins or internal notes (§44).
 *
 * If points 2 to 4 cannot be satisfied, `dally_api` stays the production path and
 * this adapter is dropped. That is a legitimate outcome, not a failure — which is
 * precisely why the interface exists.
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
  'The JSON-2 adapter is not implemented: the protocol has not been validated ' +
  'against a running Odoo 19 instance (see phase 3). Set ' +
  'ODOO_GATEWAY_ADAPTER=dally_api.';

export class Json2Adapter implements OdooGateway {
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
