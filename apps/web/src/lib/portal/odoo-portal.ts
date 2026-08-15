/**
 * La passerelle portail — délibérément incapable d'utiliser une clé d'API.
 *
 * ## Pourquoi une seconde passerelle plutôt qu'un paramètre
 *
 * `DallyApiAdapter` parle à Odoo avec `X-API-Key` et agit sous un utilisateur
 * d'intégration. Ajouter à cette classe un mode « session utilisateur » aurait été
 * plus court, et aurait créé exactement le bug qu'on veut rendre impossible : un
 * appel portail qui, par un argument oublié ou un repli sur erreur, repartirait
 * avec la clé de service et lirait les dossiers de tout le monde.
 *
 * Les deux passerelles sont donc des types distincts, sans base commune. Ce fichier
 * n'importe jamais `getServerEnv().ODOO_API_KEY*` : la confusion n'est pas
 * découragée, elle est absente du code.
 *
 * ## Ce que cette passerelle transporte
 *
 * Un `Cookie: session_id=…` et rien d'autre. Odoo reconstitue l'utilisateur, ses
 * groupes et ses record rules à partir de là. Le BFF n'ajoute aucun `partner_id`,
 * aucun domaine, aucun filtre : il n'a rien à ajouter, et tout ce qu'il ajouterait
 * serait une décision de sécurité prise du mauvais côté.
 */

import { getServerEnv } from '@/lib/env';
import { logger } from '@/lib/logger';

/** Codes stables, pour que l'appelant décide sans analyser un message. */
export type PortalErrorCode =
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'invalid_credentials'
  | 'unavailable'
  | 'timeout';

export class PortalGatewayError extends Error {
  constructor(
    readonly code: PortalErrorCode,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'PortalGatewayError';
  }
}

interface OdooEnvelope<T> {
  readonly success?: boolean;
  readonly data?: T;
  readonly error?: { readonly code?: string; readonly message?: string };
}

interface JsonRpcEnvelope<T> {
  readonly result?: T;
  readonly error?: { readonly message?: string; readonly data?: unknown };
}

/**
 * Nettoie une valeur avant de l'écrire dans un en-tête `Cookie`.
 *
 * L'identifiant vient d'Odoo, donc d'une source de confiance — mais il traverse un
 * en-tête, et une valeur contenant un retour chariot y injecterait une seconde
 * ligne. Le coût du contrôle est nul ; celui de l'oubli ne l'est pas.
 */
function safeSessionId(sessionId: string): string {
  if (!/^[A-Za-z0-9_-]{8,256}$/.test(sessionId)) {
    throw new PortalGatewayError('unauthenticated', 'malformed session id');
  }
  return sessionId;
}

export class PortalOdooGateway {
  private readonly baseUrl: string;
  private readonly database: string;
  private readonly timeoutMs: number;

  constructor() {
    const env = getServerEnv();
    this.baseUrl = env.ODOO_URL.replace(/\/+$/, '');
    this.database = env.ODOO_DATABASE;
    this.timeoutMs = env.ODOO_TIMEOUT_MS;
  }

  /** Appel brut, avec délai borné et erreurs normalisées. */
  private async call(
    path: string,
    init: {
      method: 'GET' | 'POST';
      body?: unknown;
      sessionId?: string;
      /** Ne pas consommer le corps en texte — voir `download`. */
      raw?: boolean;
    },
    correlationId: string,
  ): Promise<{ response: Response; text: string }> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const startedAt = Date.now();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (init.sessionId) {
      headers.Cookie = `session_id=${safeSessionId(init.sessionId)}`;
    }
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        method: init.method,
        headers,
        ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
        // Jamais de cache : ces réponses sont propres à un client.
        cache: 'no-store',
        redirect: 'manual',
        signal: controller.signal,
      });
      // Un fichier n'est pas du texte : le lire en UTF-8 corromprait un PDF.
      return { response, text: init.raw ? '' : await response.text() };
    } catch (error) {
      const durationMs = Date.now() - startedAt;
      const aborted = error instanceof Error && error.name === 'AbortError';
      // Ni l'URL interne, ni l'en-tête Cookie, ni le corps ne sont journalisés :
      // seulement de quoi corréler et mesurer.
      logger.error('Portal Odoo call failed', {
        correlationId, path, durationMs, aborted,
      });
      throw new PortalGatewayError(
        aborted ? 'timeout' : 'unavailable',
        'The ERP is unreachable.',
      );
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Authentifie et renvoie l'identifiant de session émis par Odoo.
   *
   * Le mot de passe n'existe que dans l'argument de cette méthode et dans le corps
   * de la requête sortante. Il n'est ni conservé, ni journalisé, ni renvoyé.
   */
  async authenticate(
    login: string,
    password: string,
    correlationId: string,
  ): Promise<string> {
    const { response, text } = await this.call(
      '/web/session/authenticate',
      {
        method: 'POST',
        body: {
          jsonrpc: '2.0',
          method: 'call',
          params: { db: this.database, login, password },
        },
      },
      correlationId,
    );

    let envelope: JsonRpcEnvelope<{ uid?: number | false }> | null = null;
    try {
      envelope = JSON.parse(text) as JsonRpcEnvelope<{ uid?: number | false }>;
    } catch {
      throw new PortalGatewayError('unavailable', 'unreadable ERP response');
    }
    if (envelope.error || !envelope.result?.uid) {
      // Un identifiant inconnu et un mot de passe faux produisent le même code :
      // l'appelant ne doit pas pouvoir distinguer les deux.
      throw new PortalGatewayError('invalid_credentials', 'authentication failed');
    }

    const sessionId = this.readSessionCookie(response);
    if (!sessionId) {
      throw new PortalGatewayError('unavailable', 'no session issued');
    }
    return sessionId;
  }

  /** Extrait `session_id` des `Set-Cookie` de la réponse Odoo. */
  private readSessionCookie(response: Response): string | null {
    const raw =
      typeof response.headers.getSetCookie === 'function'
        ? response.headers.getSetCookie()
        : [response.headers.get('set-cookie') ?? ''];
    for (const cookie of raw) {
      const match = /(?:^|;\s*)session_id=([^;]+)/.exec(cookie ?? '');
      if (match?.[1]) return match[1];
    }
    return null;
  }

  /** Détruit la session côté Odoo. Idempotent : une session absente n'est pas une erreur. */
  async destroySession(sessionId: string, correlationId: string): Promise<void> {
    try {
      await this.call(
        '/web/session/destroy',
        {
          method: 'POST',
          sessionId,
          body: { jsonrpc: '2.0', method: 'call', params: {} },
        },
        correlationId,
      );
    } catch {
      // Odoo injoignable ou session déjà morte : le cookie local sera supprimé de
      // toute façon. Faire échouer une déconnexion laisserait l'utilisateur avec
      // un cookie qu'il ne peut plus retirer.
    }
  }

  /**
   * Appelle un endpoint `/api/v1/portal/*` sous la session du client.
   *
   * Aucun repli : si la session est refusée, l'appel échoue. Rejouer avec une clé
   * d'intégration donnerait une réponse — celle d'un autre utilisateur.
   */
  async get<T>(
    path: string,
    sessionId: string,
    correlationId: string,
  ): Promise<T> {
    const { response, text } = await this.call(
      `/api/v1/portal${path}`,
      { method: 'GET', sessionId },
      correlationId,
    );

    if (response.status === 401 || response.status === 403) {
      throw new PortalGatewayError(
        'unauthenticated', 'session rejected', response.status,
      );
    }
    // Odoo redirige vers /web/login quand la session a expiré : une redirection
    // est donc une session morte, pas une ressource déplacée.
    if (response.status >= 300 && response.status < 400) {
      throw new PortalGatewayError('unauthenticated', 'session expired');
    }
    if (response.status === 404) {
      throw new PortalGatewayError('not_found', 'not found', 404);
    }
    if (!response.ok) {
      throw new PortalGatewayError('unavailable', 'ERP error', response.status);
    }

    let envelope: OdooEnvelope<T>;
    try {
      envelope = JSON.parse(text) as OdooEnvelope<T>;
    } catch {
      throw new PortalGatewayError('unavailable', 'unreadable ERP response');
    }
    if (!envelope.success || envelope.data === undefined) {
      throw new PortalGatewayError('unavailable', 'unexpected ERP payload');
    }
    return envelope.data;
  }

  /**
   * Télécharge un fichier sous la session du client.
   *
   * Le nom de fichier vient d'Odoo, qui l'a déjà assaini (il n'en garde que des
   * caractères alphanumériques, espaces, points, tirets et soulignés). On le
   * réassainit malgré tout ici : ce nom finit dans un en-tête `Content-Disposition`
   * que nous écrivons, et faire confiance à l'assainissement d'une autre couche
   * est précisément la façon dont ces défauts reviennent.
   *
   * Le type MIME d'Odoo n'est pas repris : il renvoie `application/octet-stream`
   * pour tout, délibérément, afin qu'un fichier téléversé ne puisse pas se faire
   * interpréter comme du HTML par le navigateur.
   */
  async download(
    path: string,
    sessionId: string,
    correlationId: string,
  ): Promise<{ body: ArrayBuffer; filename: string }> {
    const { response } = await this.call(
      `/api/v1/portal${path}`,
      { method: 'GET', sessionId, raw: true },
      correlationId,
    );

    if (response.status === 401 || response.status === 403) {
      throw new PortalGatewayError('unauthenticated', 'session rejected', response.status);
    }
    if (response.status >= 300 && response.status < 400) {
      throw new PortalGatewayError('unauthenticated', 'session expired');
    }
    if (response.status === 404) {
      throw new PortalGatewayError('not_found', 'not found', 404);
    }
    if (!response.ok) {
      throw new PortalGatewayError('unavailable', 'ERP error', response.status);
    }

    return {
      body: await response.arrayBuffer(),
      filename: safeFilename(response.headers.get('content-disposition')),
    };
  }
}

/** Nom de fichier réduit à ce qui ne peut pas casser un en-tête. */
export function safeFilename(contentDisposition: string | null): string {
  const match = /filename="([^"]*)"/.exec(contentDisposition ?? '');
  const cleaned = (match?.[1] ?? '')
    .replace(/[^A-Za-z0-9 ._-]/g, '')
    .trim()
    .slice(0, 120);
  return cleaned || 'document';
}

/** Identité renvoyée par `/api/v1/portal/me`. Projection Odoo, jamais reconstruite. */
export interface PortalIdentity {
  readonly name: string;
  readonly email: string | null;
  readonly phone: string | null;
  readonly company: string | null;
  readonly city: string | null;
  readonly country: string | null;
}
