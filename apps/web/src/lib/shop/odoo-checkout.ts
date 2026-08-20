/**
 * La passerelle de commande — deux transports, jamais mélangés.
 *
 * `placeGuestOrder` utilise uniquement la clé `shop:checkout` ;
 * `placeCustomerOrder` utilise uniquement la session portail. Le corps est
 * reconstruit champ par champ. Au Lot C, le code de méthode et l'adresse de
 * livraison peuvent partir vers Odoo, mais aucun frais ni prix ne le peut.
 */

import { getServerEnv } from '@/lib/env';
import { logger } from '@/lib/logger';
import {
  shopOrderSchema,
  type DeliveryMode,
  type GuestCustomer,
  type ShopOrder,
} from './checkout-schema';
import type { CartLine } from './cart';
import type { ShippingAddress } from './delivery';

export type CheckoutErrorCode =
  | 'unauthenticated'
  | 'forbidden'
  | 'invalid_checkout'
  | 'forbidden_fields'
  | 'unavailable_products'
  | 'portal_account_exists'
  | 'empty_cart'
  | 'shop_unavailable'
  | 'shop_pricelist_missing'
  | 'rate_limited'
  | 'unavailable'
  | 'timeout'
  | 'invalid_response'
  | 'misconfigured';

export class CheckoutGatewayError extends Error {
  constructor(
    readonly code: CheckoutErrorCode,
    message: string,
    readonly status?: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = 'CheckoutGatewayError';
  }
}

interface Enveloppe {
  readonly success?: boolean;
  readonly data?: { readonly order?: unknown };
  readonly error?: { readonly code?: string; readonly message?: string };
}

/** Ce qui part vers Odoo. Reconstruit, jamais relayé tel quel. */
interface Demande {
  readonly cartId: string;
  readonly deliveryMode: DeliveryMode;
  readonly lines: readonly CartLine[];
  readonly customer?: GuestCustomer;
  readonly shipping?: ShippingAddress;
}

export class ShopCheckoutGateway {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor() {
    const env = getServerEnv();
    this.baseUrl = env.ODOO_URL.replace(/\/+$/, '');
    this.timeoutMs = env.ODOO_TIMEOUT_MS;
  }

  async placeGuestOrder(
    demande: Demande & { customer: GuestCustomer },
    correlationId: string,
  ): Promise<ShopOrder> {
    const clef = getServerEnv().ODOO_API_KEY_SHOP_CHECKOUT;
    if (!clef) {
      throw new CheckoutGatewayError(
        'misconfigured',
        'ODOO_API_KEY_SHOP_CHECKOUT is not configured.',
      );
    }
    return this.appeler(
      '/api/v1/shop/checkout',
      this.corps(demande),
      { 'X-API-Key': clef },
      correlationId,
    );
  }

  async placeCustomerOrder(
    demande: Demande,
    odooSessionId: string,
    correlationId: string,
  ): Promise<ShopOrder> {
    return this.appeler(
      '/api/v1/portal/shop/checkout',
      this.corps(demande),
      { Cookie: `session_id=${sessionSure(odooSessionId)}` },
      correlationId,
    );
  }

  /**
   * Construit le corps envoyé à Odoo, champ par champ.
   *
   * Ni `feeAmount`, ni `price_unit`, ni total ne sont copiés. Une adresse n'est
   * incluse que si le BFF l'a validée contre son schéma strict.
   */
  private corps(demande: Demande): Record<string, unknown> {
    const corps: Record<string, unknown> = {
      cartId: demande.cartId,
      deliveryMode: demande.deliveryMode,
      lines: demande.lines.map((ligne) => ({
        reference: ligne.reference,
        quantity: ligne.quantity,
      })),
    };
    if (demande.customer) {
      corps.customer = {
        name: demande.customer.name,
        email: demande.customer.email,
        ...(demande.customer.phone ? { phone: demande.customer.phone } : {}),
        ...(demande.customer.street ? { street: demande.customer.street } : {}),
        ...(demande.customer.city ? { city: demande.customer.city } : {}),
        ...(demande.customer.zip ? { zip: demande.customer.zip } : {}),
        ...(demande.customer.country_code
          ? { country_code: demande.customer.country_code }
          : {}),
      };
    }
    if (demande.shipping) {
      corps.shipping = {
        ...(demande.shipping.name ? { name: demande.shipping.name } : {}),
        ...(demande.shipping.phone ? { phone: demande.shipping.phone } : {}),
        ...(demande.shipping.street ? { street: demande.shipping.street } : {}),
        ...(demande.shipping.street2 ? { street2: demande.shipping.street2 } : {}),
        ...(demande.shipping.city ? { city: demande.shipping.city } : {}),
        ...(demande.shipping.zip ? { zip: demande.shipping.zip } : {}),
        ...(demande.shipping.country_code
          ? { country_code: demande.shipping.country_code }
          : {}),
      };
    }
    return corps;
  }

  private async appeler(
    chemin: string,
    corps: Record<string, unknown>,
    entetes: Record<string, string>,
    correlationId: string,
  ): Promise<ShopOrder> {
    const controleur = new AbortController();
    const minuteur = setTimeout(() => controleur.abort(), this.timeoutMs);
    const debut = Date.now();

    try {
      const reponse = await fetch(`${this.baseUrl}${chemin}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Correlation-Id': correlationId,
          ...entetes,
        },
        body: JSON.stringify(corps),
        cache: 'no-store',
        redirect: 'manual',
        signal: controleur.signal,
      });

      const texte = await reponse.text();
      let enveloppe: Enveloppe | null = null;
      try {
        enveloppe = texte ? (JSON.parse(texte) as Enveloppe) : null;
      } catch {
        throw new CheckoutGatewayError(
          'unauthenticated',
          'session rejected by the ERP',
          reponse.status,
        );
      }

      if (!reponse.ok || enveloppe?.success !== true) {
        throw this.erreurMetier(reponse.status, enveloppe, correlationId, chemin);
      }

      return this.valider(enveloppe.data?.order, correlationId);
    } catch (erreur) {
      if (erreur instanceof CheckoutGatewayError) throw erreur;
      const dureeMs = Date.now() - debut;
      const abandonne = erreur instanceof Error && erreur.name === 'AbortError';
      logger.error('Shop checkout call failed', {
        correlationId,
        chemin,
        dureeMs,
        abandonne,
      });
      throw new CheckoutGatewayError(
        abandonne ? 'timeout' : 'unavailable',
        'The ERP is unreachable.',
      );
    } finally {
      clearTimeout(minuteur);
    }
  }

  private erreurMetier(
    statut: number,
    enveloppe: Enveloppe | null,
    correlationId: string,
    chemin: string,
  ): CheckoutGatewayError {
    const code = enveloppe?.error?.code;
    const connus: readonly CheckoutErrorCode[] = [
      'invalid_checkout',
      'forbidden_fields',
      'unavailable_products',
      'portal_account_exists',
      'empty_cart',
      'shop_unavailable',
      'shop_pricelist_missing',
    ];
    if (code && (connus as readonly string[]).includes(code)) {
      return new CheckoutGatewayError(
        code as CheckoutErrorCode,
        code,
        statut,
        enveloppe?.error?.message,
      );
    }
    if (statut === 401) {
      return new CheckoutGatewayError('unauthenticated', 'not authenticated', 401);
    }
    if (statut === 403) {
      logger.error('Shop checkout rejected by Odoo', {
        correlationId,
        chemin,
        statut,
        code,
      });
      return new CheckoutGatewayError('forbidden', 'rejected', 403);
    }
    if (statut === 429) {
      return new CheckoutGatewayError('rate_limited', 'rate limited', 429);
    }
    logger.error('Shop checkout unexpected ERP response', {
      correlationId,
      chemin,
      statut,
      code,
    });
    return new CheckoutGatewayError('unavailable', code ?? `HTTP ${statut}`, statut);
  }

  private valider(brut: unknown, correlationId: string): ShopOrder {
    const resultat = shopOrderSchema.safeParse(brut);
    if (!resultat.success) {
      logger.error('Shop order failed its contract', {
        correlationId,
        issues: String(resultat.error),
      });
      throw new CheckoutGatewayError('invalid_response', 'unexpected ERP payload');
    }
    return resultat.data;
  }
}

function sessionSure(valeur: string): string {
  if (!/^[A-Za-z0-9_-]{8,256}$/.test(valeur)) {
    throw new CheckoutGatewayError('unauthenticated', 'malformed session id');
  }
  return valeur;
}
