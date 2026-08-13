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

/**
 * A service offered, as published by `GET /api/v1/services`.
 *
 * Odoo is the source of truth: these flags are what decide which steps and fields
 * the quote form shows. The website holds no second business list.
 *
 * Field names mirror the API payload (snake_case) rather than being camelised.
 * The contract is stated once, in Odoo, and repeating it here in a different
 * spelling would mean two names for every flag and a mapping layer to keep in
 * step — for no gain.
 */
export interface ServiceType {
  readonly code: string;
  readonly name: string;
  readonly description: string;
  readonly active: boolean;
  readonly sort_order: number;
  readonly requires_origin: boolean;
  readonly requires_destination: boolean;
  readonly requires_weight: boolean;
  readonly requires_volume: boolean;
  readonly requires_vehicle: boolean;
  readonly requires_budget: boolean;
  readonly requires_goods: boolean;
}

/** A quote request submitted from the public site. */
export interface QuoteInput {
  readonly serviceCode: string;
  readonly firstName?: string;
  readonly lastName: string;
  readonly companyName?: string;
  readonly email?: string;
  readonly phone?: string;
  readonly whatsapp?: string;
  readonly city?: string;
  readonly countryCode?: string;
  readonly originCountryCode?: string;
  readonly originCity?: string;
  readonly destinationCountryCode?: string;
  readonly destinationCity?: string;
  readonly goodsDescription?: string;
  readonly quantity?: string;
  readonly weightKg?: number;
  readonly volumeCbm?: number;
  readonly packagesCount?: number;
  readonly vehicleMake?: string;
  readonly vehicleModel?: string;
  readonly vehicleYear?: string;
  readonly budget?: string;
  readonly message?: string;
  readonly sourceUrl?: string;
  readonly referrerUrl?: string;
  readonly utmSource?: string;
  readonly utmMedium?: string;
  readonly utmCampaign?: string;
}

/** What the customer is shown after submitting a quote request. */
export interface QuoteRef {
  readonly reference: string;
  readonly serviceCode: string | null;
  readonly status: 'received';
}

/**
 * A sourcing request submitted from the public site.
 *
 * Nested to match the API contract, which groups customer and product because they
 * are filled on different steps of the form and travel together.
 *
 * Note what is absent: nothing about suppliers, offers, costs or margins. Those exist
 * only inside Odoo, on models the sourcing API user cannot reach.
 */
export interface SourcingRequestInput {
  readonly serviceCode?: string;
  readonly customer: {
    readonly firstName?: string;
    readonly lastName: string;
    readonly company?: string;
    readonly email?: string;
    readonly phone?: string;
    readonly whatsapp?: string;
  };
  readonly product: {
    readonly name: string;
    readonly description?: string;
    readonly specifications?: string;
    readonly reference?: string;
    readonly url?: string;
  };
  readonly quantity: number;
  readonly uom?: string;
  readonly budget?: number;
  readonly targetUnitPrice?: number;
  readonly currency?: string;
  readonly preferredOriginCountry?: string;
  readonly destinationCountry?: string;
  readonly requestedDeadline?: string;
  readonly requiredDeliveryDate?: string;
  readonly notes?: string;
  readonly sourceUrl?: string;
  readonly referrerUrl?: string;
  readonly utm?: {
    readonly source?: string;
    readonly medium?: string;
    readonly campaign?: string;
  };
}

/** What the customer is shown after submitting a sourcing request. */
export interface SourcingRequestRef {
  /** Business reference, e.g. DT-SRC-2026-000124. */
  readonly reference: string;
  readonly serviceCode: string | null;
  readonly status: 'received';
}

/**
 * A trade enquiry, as the public site may express it.
 *
 * Note what is absent, and why. There is no purchase price, no cost, no margin, no
 * commission and no supplier: those exist only inside Odoo, on fields the trade API
 * user cannot load. If one of them ever appears in this interface, the leak happened
 * at design time, not at runtime.
 *
 * `operationType` mirrors the six types the module declares. It is a union rather
 * than a string so a typo is a compile error instead of a 422 in production.
 */
export type TradeOperationType =
  | 'purchase_resale'
  | 'brokerage'
  | 'commission'
  | 'distribution'
  | 'import_export'
  | 'commercial_representation';

export interface TradeOpportunityInput {
  readonly operationType: TradeOperationType;
  readonly subject: string;
  readonly description?: string;
  readonly requirements?: string;
  readonly serviceCode?: string;
  readonly contact: {
    readonly name: string;
    readonly company?: string;
    readonly email?: string;
    readonly phone?: string;
    readonly whatsapp?: string;
    readonly country?: string;
  };
  readonly originCountry?: string;
  readonly destinationCountry?: string;
  readonly sourceUrl?: string;
  readonly referrerUrl?: string;
}

/** What the enquirer is shown after submitting. */
export interface TradeOpportunityRef {
  /** Business reference, e.g. DT-TRD-2026-000031. */
  readonly reference: string;
  readonly operationType: TradeOperationType;
  readonly status: 'received';
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
