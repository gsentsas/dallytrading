/**
 * The gateway interface (ADR-008).
 *
 * Everything the site needs from Odoo goes through this one interface. Odoo 19
 * introduces the JSON-2 API and marks XML-RPC / JSON-RPC as deprecated; binding
 * the application directly to any of them would mean rewriting call sites when
 * that landscape shifts. Here, a protocol change is one new implementation.
 *
 * Rules for implementers:
 *
 * - Every method either returns the documented type or throws `OdooGatewayError`.
 *   No implementation-specific exception may escape.
 * - `createLead` **must** be idempotent on `idempotencyKey`: calling it twice with
 *   the same key returns the same `LeadRef` and creates one record (§41).
 * - Nothing returned may contain an Odoo database id (§42).
 */

import type {
  LeadInput,
  LeadRef,
  PublicShipment,
  QuoteInput,
  QuoteRef,
  ServiceType,
  SourcingRequestInput,
  SourcingRequestRef,
  TradeOpportunityInput,
  TradeOpportunityRef,
  ReferenceEntry,
} from './types';

export interface OdooGateway {
  /**
   * Create a quote request from a public submission.
   *
   * Produces a qualifiable request and a CRM opportunity — never a quotation, a
   * contact or a shipment. Those follow human qualification.
   *
   * Must be idempotent on `idempotencyKey`, like `createLead`.
   */
  createQuoteRequest(
    input: QuoteInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<QuoteRef>;

  /**
   * Create a lead from a public submission.
   *
   * @param input Validated request data.
   * @param idempotencyKey A UUID generated per submission attempt. The same key
   *   must never produce a second lead — this is what makes a double-click or a
   *   network retry safe.
   * @param correlationId Propagated into logs on both sides.
   */
  createLead(
    input: LeadInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<LeadRef>;

  /**
   * Create a sourcing request from a public submission.
   *
   * Produces a qualifiable request and nothing else — no contact, no CRM
   * opportunity, no supplier, no purchase order. Those follow human qualification.
   *
   * Must be idempotent on `idempotencyKey`, like the other create methods.
   */
  createSourcingRequest(
    input: SourcingRequestInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<SourcingRequestRef>;

  /**
   * Create a trade opportunity from a public enquiry.
   *
   * Produces a qualifiable deal in `draft` — never a purchase order, a sales order,
   * a contact or a shipment. Those follow human qualification, and several of them
   * only ever exist for some operation types.
   *
   * Must be idempotent on `idempotencyKey`, like the other write paths.
   */
  createTradeOpportunity(
    input: TradeOpportunityInput,
    idempotencyKey: string,
    correlationId: string,
  ): Promise<TradeOpportunityRef>;

  /**
   * Look up a shipment by reference **and** tracking token.
   *
   * Both are required. References are sequential and therefore walkable; the token
   * is what makes the lookup a capability rather than a guess.
   *
   * Returns `null` when unknown, rather than throwing: a wrong reference is a
   * normal outcome of a customer typing one in, not an error condition. An unknown
   * reference and a wrong token must be indistinguishable, so the endpoint cannot
   * be used to confirm which references exist.
   */
  getShipmentByTracking(
    reference: string,
    token: string,
    correlationId: string,
  ): Promise<PublicShipment | null>;

  /**
   * Services published for the public quote form.
   *
   * Odoo is the source of truth. Callers should go through
   * `getServiceCatalogue()` rather than calling this directly, so they benefit
   * from caching and the stale-on-error fallback.
   */
  listServiceTypes(correlationId: string): Promise<ReadonlyArray<ServiceType>>;

  /**
   * Un référentiel public : pays, subdivisions, lieux desservis, incoterms.
   *
   * `param` est le seul argument que le référentiel accepte — le code pays
   * pour les subdivisions, le mode pour les lieux — et il est ignoré par les
   * autres. Le contenu n'est jamais commercial : ni transporteur, ni
   * compagnie, ni tarif.
   */
  listReferences(
    kind: string,
    param: string | undefined,
    correlationId: string,
  ): Promise<ReadonlyArray<ReferenceEntry>>;

  /** Liveness probe used by monitoring and by deployment smoke tests. */
  healthCheck(correlationId: string): Promise<{ ok: boolean; database?: string }>;
}
