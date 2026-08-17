/**
 * La passerelle de commande — deux transports, jamais mélangés.
 *
 * ## Pourquoi une troisième passerelle
 *
 * Le dépôt en compte déjà deux, et pour la même raison qui en impose une
 * troisième : `DallyApiAdapter` parle avec une clé d'intégration,
 * `PortalOdooGateway` avec une session client, et les deux sont des types
 * distincts sans base commune afin qu'un appel ne puisse pas repartir avec le
 * mauvais pouvoir « par un argument oublié ou un repli sur erreur ».
 *
 * Celle-ci suit la même règle et l'applique à l'intérieur d'elle-même. Elle
 * expose deux méthodes :
 *
 * * `placeGuestOrder` — clé `ODOO_API_KEY_SHOP_CHECKOUT`, aucune session ;
 * * `placeCustomerOrder` — session portail, **aucune clé d'API**.
 *
 * Chaque méthode construit ses propres en-têtes. Il n'existe aucun chemin de code
 * où une session et une clé partent ensemble, et aucun où la clé de lecture
 * (`ODOO_API_KEY_SHOP_READ`) serait utilisée pour écrire.
 *
 * ## Aucun repli
 *
 * Ni l'une ni l'autre ne retombe sur `ODOO_API_KEY`. Un repli laisserait la
 * boutique fonctionner sous une identité capable d'écrire des prospects et de
 * lire des dossiers clients, sans que rien ne le signale. Une clé absente est une
 * panne.
 */

import { getServerEnv } from '@/lib/env';
import { logger } from '@/lib/logger';
import { shopOrderSchema, type DeliveryMode, type GuestCustomer, type ShopOrder } from './checkout-schema';
import type { CartLine } from './cart';

/** Codes stables, pour que l'appelant décide sans analyser un message. */
export type CheckoutErrorCode =
  | 'unauthenticated'
  | 'forbidden'
  | 'invalid_checkout'
  | 'forbidden_fields'
  | 'unavailable_products'
  | 'portal_account_exists'
  | 'empty_cart'
  | 'shop_unavailable'
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
    /** Détail sûr à montrer au client, quand il y en a un. */
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
}

export class ShopCheckoutGateway {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor() {
    const env = getServerEnv();
    this.baseUrl = env.ODOO_URL.replace(/\/+$/, '');
    this.timeoutMs = env.ODOO_TIMEOUT_MS;
  }

  /**
   * Commande d'un invité.
   *
   * La clé est lue ici et non dans le constructeur : la passerelle doit pouvoir
   * servir un client connecté même si la clé invité n'est pas configurée, et
   * l'inverse. Deux capacités, deux pannes distinctes.
   */
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

  /**
   * Commande d'un client connecté.
   *
   * Aucune clé d'API n'est jointe, et c'est le cœur du dispositif : la seule
   * chose transportée est `Cookie: session_id=…`. Odoo reconstitue l'utilisateur,
   * ses groupes et ses record rules, et `request.env.user.partner_id` est le
   * client. Aucun `partner_id` n'est envoyé, donc aucun n'est à valider.
   */
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
   * Reconstruit et non relayé : ce qui part contient alors exactement les clés
   * attendues, quelle que soit la forme de l'objet reçu en amont. Aucun prix,
   * aucune remise, aucun identifiant de client ne peut s'y glisser, même par
   * accident de refactoring.
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
        // `manual` : une route Odoo en `auth="user"` sans session valide répond
        // par une redirection vers sa page de connexion. La suivre ramènerait du
        // HTML qu'on interpréterait comme une réponse d'API.
        redirect: 'manual',
        signal: controleur.signal,
      });

      const texte = await reponse.text();
      let enveloppe: Enveloppe | null = null;
      try {
        enveloppe = texte ? (JSON.parse(texte) as Enveloppe) : null;
      } catch {
        // Réponse non-JSON. Sur ces routes, c'est la page de connexion d'Odoo :
        // la session est absente ou expirée. Mesuré sur l'instance de
        // développement — Odoo répond 200 avec du HTML, pas 401.
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
      // Ni l'URL interne, ni les en-têtes, ni le corps : seulement de quoi
      // corréler et mesurer.
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

  /**
   * Traduit une erreur d'Odoo en code stable.
   *
   * Les codes métier sont repris tels quels quand ils existent : ils viennent de
   * notre propre contrôleur, ils sont stables, et les réinventer d'après le
   * statut HTTP perdrait la distinction entre « produits indisponibles » et
   * « un compte existe déjà », qui appellent deux messages très différents.
   */
  private erreurMetier(
    statut: number,
    enveloppe: Enveloppe | null,
    correlationId: string,
    chemin: string,
  ): CheckoutGatewayError {
    const code = enveloppe?.error?.code;
    const connus: readonly CheckoutErrorCode[] = [
      'invalid_checkout', 'forbidden_fields', 'unavailable_products',
      'portal_account_exists', 'empty_cart', 'shop_unavailable',
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
      // Une clé rejetée est une panne d'exploitation, pas une erreur du visiteur.
      logger.error('Shop checkout rejected by Odoo', { correlationId, chemin, statut, code });
      return new CheckoutGatewayError('forbidden', 'rejected', 403);
    }
    if (statut === 429) {
      return new CheckoutGatewayError('rate_limited', 'rate limited', 429);
    }
    logger.error('Shop checkout unexpected ERP response', {
      correlationId, chemin, statut, code,
    });
    return new CheckoutGatewayError('unavailable', code ?? `HTTP ${statut}`, statut);
  }

  /** Valide la commande contre son contrat, sans révéler la forme interne. */
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

/**
 * Un identifiant de session ne franchit un en-tête que s'il en a la forme.
 *
 * Le même contrôle que dans la passerelle portail : un identifiant contenant un
 * retour à la ligne permettrait d'injecter un en-tête supplémentaire dans la
 * requête sortante.
 *
 * Les bornes sont **identiques** à celles de `safeSessionId` dans
 * `lib/portal/odoo-portal.ts` (`{8,256}`), et non resserrées « par prudence » :
 * deux jeux de bornes divergents finiraient par refuser ici une session que le
 * portail accepte, et le symptôme — une commande impossible pour un client
 * pourtant connecté — n'aurait aucun rapport visible avec la cause.
 */
function sessionSure(valeur: string): string {
  if (!/^[A-Za-z0-9_-]{8,256}$/.test(valeur)) {
    throw new CheckoutGatewayError('unauthenticated', 'malformed session id');
  }
  return valeur;
}
