/**
 * La passerelle boutique — un seul scope, et une seule identité.
 *
 * ## Pourquoi une passerelle dédiée
 *
 * La vitrine est la surface la plus exposée du site : anonyme, indexée, appelée
 * par n'importe qui. Elle n'a besoin que de lire un catalogue public. Lui donner
 * la clé qui écrit des prospects et lit des dossiers clients serait accorder à la
 * page la plus attaquable la clé la plus large.
 *
 * ## Aucun repli
 *
 * `ODOO_API_KEY_SHOP_READ` ne porte que `shop:read`, et son absence **ne retombe
 * pas** sur `ODOO_API_KEY`. Un repli serait commode et irait dans le mauvais
 * sens : la boutique continuerait de fonctionner, sous une identité capable
 * d'écrire des prospects et de lire des clients, sans que rien ne le signale.
 * Une clé absente est donc une panne — bruyante au démarrage en production,
 * explicite ici partout ailleurs.
 *
 * ## Le prix ne remonte que dans un sens
 *
 * Aucune méthode de ce fichier n'envoie de prix à Odoo. `resolveCart` transmet
 * des références et des quantités ; le montant revient calculé. C'est ce qui rend
 * inutile de faire confiance au navigateur : il n'y a pas de valeur à valider,
 * parce qu'il n'y a pas de valeur reçue.
 */

import { getServerEnv } from '@/lib/env';
import { logger } from '@/lib/logger';
import {
  resolvedCartSchema,
  shopCatalogueSchema,
  shopProductDetailSchema,
  type ResolvedCart,
  type ShopCatalogue,
  type ShopProductDetail,
} from './dto';
import type { CartLine } from './cart';

/** Codes stables, pour que l'appelant décide sans analyser un message. */
export type ShopErrorCode =
  | 'not_found'
  | 'unavailable'
  | 'timeout'
  | 'invalid_response'
  | 'forbidden'
  /** Clé absente ou secret manquant : panne d'exploitation, pas erreur client. */
  | 'misconfigured';

export class ShopGatewayError extends Error {
  constructor(
    readonly code: ShopErrorCode,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ShopGatewayError';
  }
}

interface OdooEnvelope<T> {
  readonly success?: boolean;
  readonly data?: T;
  readonly error?: { readonly code?: string; readonly message?: string };
}

export class ShopOdooGateway {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;

  constructor() {
    const env = getServerEnv();
    this.baseUrl = env.ODOO_URL.replace(/\/+$/, '');
    this.timeoutMs = env.ODOO_TIMEOUT_MS;
    // Pas de `??` : l'absence de clé est une erreur de configuration, et la
    // remplacer par une clé plus large serait exactement le repli qu'on refuse.
    if (!env.ODOO_API_KEY_SHOP_READ) {
      throw new ShopGatewayError(
        'misconfigured',
        'ODOO_API_KEY_SHOP_READ is not configured.',
      );
    }
    this.apiKey = env.ODOO_API_KEY_SHOP_READ;
  }

  private async call<T>(
    path: string,
    init: { method: 'GET' | 'POST'; body?: unknown },
    correlationId: string,
  ): Promise<T> {
    // Un fetch sans borne laisserait un Odoo bloqué retenir un worker Next
    // jusqu'à ce que le proxy abandonne, transformant un appel lent en file
    // d'appels lents.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const startedAt = Date.now();

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: init.method,
        headers: {
          'Content-Type': 'application/json',
          // La clé reste côté serveur. Elle n'est jamais transmise au navigateur
          // et jamais journalisée — le logger occulte ce nom d'en-tête.
          'X-API-Key': this.apiKey,
          'X-Correlation-Id': correlationId,
        },
        ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
        cache: 'no-store',
        signal: controller.signal,
      });

      const text = await response.text();
      let envelope: OdooEnvelope<T> | null = null;
      try {
        envelope = text ? (JSON.parse(text) as OdooEnvelope<T>) : null;
      } catch {
        throw new ShopGatewayError('invalid_response', 'unreadable ERP response');
      }

      if (!response.ok || envelope?.success !== true) {
        // 404 est le seul cas que l'appelant distingue, et il vaut aussi bien
        // pour un produit inconnu que pour un produit non publié : Odoo répond
        // la même chose aux deux, et cette passerelle n'a pas à inventer une
        // distinction qu'on a pris soin de supprimer.
        if (response.status === 404) {
          throw new ShopGatewayError('not_found', 'not found', 404);
        }
        if (response.status === 401 || response.status === 403) {
          // Une clé mal configurée, pas une erreur du visiteur. Journalisée en
          // erreur parce que c'est une panne d'exploitation qui doit se voir.
          logger.error('Shop gateway rejected by Odoo', {
            correlationId,
            path,
            status: response.status,
            code: envelope?.error?.code,
          });
          throw new ShopGatewayError('forbidden', 'shop key rejected', response.status);
        }
        throw new ShopGatewayError(
          'unavailable',
          envelope?.error?.code ?? `HTTP ${response.status}`,
          response.status,
        );
      }

      if (envelope.data === undefined) {
        throw new ShopGatewayError('invalid_response', 'missing data');
      }
      return envelope.data;
    } catch (error) {
      if (error instanceof ShopGatewayError) throw error;
      const durationMs = Date.now() - startedAt;
      const aborted = error instanceof Error && error.name === 'AbortError';
      logger.error('Shop Odoo call failed', {
        correlationId,
        path,
        durationMs,
        aborted,
      });
      throw new ShopGatewayError(
        aborted ? 'timeout' : 'unavailable',
        'The ERP is unreachable.',
      );
    } finally {
      clearTimeout(timer);
    }
  }

  /** Le catalogue publié. */
  async getCatalogue(
    correlationId: string,
    options: { category?: string } = {},
  ): Promise<ShopCatalogue> {
    const query = options.category
      ? `?category=${encodeURIComponent(options.category)}`
      : '';
    const data = await this.call<unknown>(
      `/api/v1/shop/products${query}`,
      { method: 'GET' },
      correlationId,
    );
    return this.parse(shopCatalogueSchema, data, correlationId, 'catalogue');
  }

  /** Une fiche produit, ou `not_found` — publié ou non, la réponse est la même. */
  async getProduct(
    reference: string,
    correlationId: string,
  ): Promise<ShopProductDetail> {
    const data = await this.call<unknown>(
      `/api/v1/shop/products/${encodeURIComponent(reference)}`,
      { method: 'GET' },
      correlationId,
    );
    const parsed = this.parse(
      shopProductDetailSchema,
      (data as { product?: unknown }).product,
      correlationId,
      'product',
    );
    return parsed;
  }

  /**
   * Tarifie un panier. Les prix sont calculés par Odoo, pas transmis.
   *
   * Un panier vide n'est pas envoyé : la réponse est connue d'avance, et une
   * requête réseau par affichage de page pour obtenir un total de zéro serait du
   * gaspillage sur la page la plus visitée.
   */
  async resolveCart(
    lines: readonly CartLine[],
    correlationId: string,
  ): Promise<ResolvedCart> {
    const data = await this.call<unknown>(
      '/api/v1/shop/cart/resolve',
      {
        method: 'POST',
        // Reconstruit ligne par ligne, et non transmis tel quel : ce qui part
        // vers Odoo ne contient alors que les deux champs attendus, quelle que
        // soit la forme de l'objet reçu en amont.
        body: {
          lines: lines.map((line) => ({
            reference: line.reference,
            quantity: line.quantity,
          })),
        },
      },
      correlationId,
    );
    return this.parse(resolvedCartSchema, data, correlationId, 'cart');
  }

  /**
   * Valide une réponse contre son contrat.
   *
   * Le détail de l'échec est journalisé mais jamais renvoyé : il décrirait la
   * forme interne de la réponse d'Odoo.
   */
  private parse<T>(
    schema: { safeParse: (value: unknown) => { success: boolean; data?: T; error?: unknown } },
    value: unknown,
    correlationId: string,
    what: string,
  ): T {
    const result = schema.safeParse(value);
    if (!result.success || result.data === undefined) {
      logger.error('Shop response failed its contract', {
        correlationId,
        what,
        issues: String(result.error),
      });
      throw new ShopGatewayError('invalid_response', 'unexpected ERP payload');
    }
    return result.data;
  }
}
