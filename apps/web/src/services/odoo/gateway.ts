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

import type { LeadInput, LeadRef, PublicShipment, ServiceType } from './types';

export interface OdooGateway {
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
   * Look up a shipment by its public tracking reference.
   *
   * Returns `null` when unknown, rather than throwing: an unknown reference is a
   * normal outcome of a customer typing one in, not an error condition. It must
   * also be indistinguishable from "exists but not yours", so that the endpoint
   * cannot be used to enumerate references.
   */
  getShipmentByTracking(
    reference: string,
    correlationId: string,
  ): Promise<PublicShipment | null>;

  /** Services published for the public quote form. */
  listServiceTypes(correlationId: string): Promise<ReadonlyArray<ServiceType>>;

  /** Liveness probe used by monitoring and by deployment smoke tests. */
  healthCheck(correlationId: string): Promise<{ ok: boolean; database?: string }>;
}
