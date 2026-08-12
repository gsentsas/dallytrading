/**
 * Data contract between the website and Odoo.
 *
 * These types are the boundary. They are intentionally *not* mirrors of Odoo
 * models: exposing Odoo's shape would couple every page to the ERP schema, and
 * the point of the gateway (ADR-008) is that the ERP protocol can change without
 * the site noticing.
 *
 * Note what is absent: there is no `id` anywhere in the outbound types. A
 * sequential database id must never become an authorisation handle (§42).
 * Records are addressed by their business reference.
 */

/** A quote or contact request submitted from the public site. */
export interface LeadInput {
  readonly serviceCode: string;
  readonly firstName?: string;
  readonly lastName: string;
  readonly companyName?: string;
  readonly email?: string;
  readonly phone?: string;
  readonly whatsapp?: string;
  readonly city?: string;
  /** ISO 3166-1 alpha-2. */
  readonly countryCode?: string;
  readonly message?: string;
  /** Page the request came from, for attribution. */
  readonly sourceUrl?: string;
  readonly utmSource?: string;
  readonly utmMedium?: string;
  readonly utmCampaign?: string;
}

/** What the customer is shown after submitting. */
export interface LeadRef {
  /** Business reference, e.g. DT-2026-000124. Quoted in every later exchange. */
  readonly reference: string;
  readonly serviceCode: string | null;
  readonly status: 'received';
}

/**
 * Public tracking view of a shipment.
 *
 * Mirrors `PUBLIC_PAYLOAD_KEYS` in the `dally_tracking` module exactly. Both
 * sides are deliberately explicit: this type is the front end's statement of what
 * it expects, and the module's allowlist is the server's statement of what it
 * emits. If they diverge, that is a change someone made on purpose.
 *
 * Note what is absent: customer identity, declared value, supplier cost, margin,
 * internal notes, sales order, invoice, and any database id.
 */
export interface PublicShipment {
  readonly reference: string;
  readonly transportMode: string;
  readonly transportModeLabel: string;
  readonly origin: string | null;
  readonly destination: string | null;
  readonly status: string;
  readonly statusLabel: string;
  readonly departureDate: string | null;
  readonly estimatedArrival: string | null;
  readonly actualArrival: string | null;
  readonly lastUpdate: string | null;
  /** The customer's own shipment identifiers, printed on their documents. */
  readonly carrierTrackingNumber: string | null;
  readonly containerNumber: string | null;
  readonly goodsDescription: string | null;
  readonly packagesCount: number;
  readonly timeline: ReadonlyArray<PublicShipmentEvent>;
}

/**
 * A tracking event as shown to a customer.
 *
 * Only customer-visible events reach this type. Internal notes, supplier costs
 * and margins are filtered server-side in Odoo, not here: filtering in the
 * front end would mean the data had already left the server (§44).
 */
export interface PublicShipmentEvent {
  readonly date: string;
  readonly status: string;
  readonly statusLabel: string;
  readonly location: string | null;
  readonly description: string | null;
}

/** A service offered, as published by Odoo. */
export interface ServiceType {
  readonly code: string;
  readonly name: string;
  readonly category: string;
  readonly requiresRoute: boolean;
  readonly requiresCargo: boolean;
}

/** Stable error codes the UI can branch on without parsing messages. */
export type OdooErrorCode =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'validation_error'
  | 'rate_limited'
  | 'unavailable'
  | 'timeout'
  | 'internal_error';

/**
 * Error raised by any gateway implementation.
 *
 * Carries a stable code so route handlers map failures to HTTP statuses without
 * inspecting prose, and an optional correlation id from Odoo so a customer-facing
 * error message can reference something support can actually look up.
 */
export class OdooGatewayError extends Error {
  readonly code: OdooErrorCode;
  readonly status: number;
  readonly odooRequestId?: string;

  constructor(
    code: OdooErrorCode,
    message: string,
    status: number,
    odooRequestId?: string,
  ) {
    super(message);
    this.name = 'OdooGatewayError';
    this.code = code;
    this.status = status;
    if (odooRequestId !== undefined) {
      this.odooRequestId = odooRequestId;
    }
  }
}
