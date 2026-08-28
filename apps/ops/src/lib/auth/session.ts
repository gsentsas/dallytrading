/**
 * Le cookie de session des opérateurs.
 *
 * ## Ce que le cookie contient
 *
 * Deux champs, et deux seulement : l'identifiant de session Odoo et l'instant
 * d'émission. Pas de nom, pas de rôle, pas de capacités, pas d'acteur de
 * caisse. Tout ce que l'application affiche est relu auprès d'Odoo à chaque
 * requête, ce qui a deux conséquences voulues :
 *
 * - un droit retiré dans Odoo prend effet immédiatement, sans attendre
 *   l'expiration d'un cookie ;
 * - le cookie ne peut pas mentir sur un rôle, puisqu'il n'en porte aucun.
 *
 * ## Pourquoi un cookie distinct du portail
 *
 * `dt_ops_session` et `dt_portal_session` ne partagent ni nom ni secret. Le
 * portail est ouvert à des clients externes ; l'application terrain écrit dans
 * la caisse et dans les réceptions. Un secret compromis d'un côté ne doit pas
 * permettre de forger une session de l'autre. Le code ci-dessous est donc une
 * duplication assumée du patron du portail, pas une réutilisation : une
 * abstraction commune ferait, tôt ou tard, converger les deux secrets.
 */

import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto';

import { opsEnv, opsUsesHttps } from '@/lib/env';

export const OPS_COOKIE = 'dt_ops_session';

/** Huit heures : la durée d'un poste, pas davantage. */
export const OPS_SESSION_MAX_AGE_SECONDS = 60 * 60 * 8;

const ALGORITHME = 'aes-256-gcm';
const IV_OCTETS = 12;
const TAG_OCTETS = 16;
const VERSION = 'v1';

export interface OpsSession {
  readonly odooSessionId: string;
  /** Époque en millisecondes. */
  readonly issuedAt: number;
}

export class OpsSessionError extends Error {
  constructor(message = 'invalid session cookie') {
    super(message);
    this.name = 'OpsSessionError';
  }
}

/**
 * La clé de chiffrement, dérivée du secret configuré.
 *
 * SHA-256 donne les 32 octets exigés par AES-256 quelle que soit la longueur
 * du secret. Ce n'est pas une dérivation lente : le secret est une valeur
 * d'environnement à forte entropie, pas un mot de passe humain, et ralentir
 * la dérivation ne protégerait de rien ici.
 */
function cleDepuis(secret: string): Buffer {
  return createHash('sha256').update(secret, 'utf8').digest();
}

export function sealSession(session: OpsSession, secret = opsEnv().OPS_SESSION_SECRET): string {
  const iv = randomBytes(IV_OCTETS);
  const chiffreur = createCipheriv(ALGORITHME, cleDepuis(secret), iv);
  const chiffre = Buffer.concat([
    chiffreur.update(JSON.stringify(session), 'utf8'),
    chiffreur.final(),
  ]);
  const tag = chiffreur.getAuthTag();
  return [
    VERSION,
    iv.toString('base64url'),
    chiffre.toString('base64url'),
    tag.toString('base64url'),
  ].join('.');
}

/**
 * Relit un cookie scellé.
 *
 * Toute anomalie — format, version, longueurs, authentification, forme du
 * contenu — lève la même erreur avec le même message. Distinguer « mauvais
 * format » de « signature invalide » offrirait un oracle à qui teste des
 * cookies fabriqués.
 */
export function unsealSession(valeur: string, secret = opsEnv().OPS_SESSION_SECRET): OpsSession {
  try {
    const parties = valeur.split('.');
    if (parties.length !== 4) throw new OpsSessionError();
    const [version, ivB64, chiffreB64, tagB64] = parties as [string, string, string, string];
    if (version !== VERSION) throw new OpsSessionError();

    const iv = Buffer.from(ivB64, 'base64url');
    const tag = Buffer.from(tagB64, 'base64url');
    if (iv.length !== IV_OCTETS || tag.length !== TAG_OCTETS) throw new OpsSessionError();

    const dechiffreur = createDecipheriv(ALGORITHME, cleDepuis(secret), iv);
    dechiffreur.setAuthTag(tag);
    const clair = Buffer.concat([
      dechiffreur.update(Buffer.from(chiffreB64, 'base64url')),
      dechiffreur.final(),
    ]).toString('utf8');

    const contenu: unknown = JSON.parse(clair);
    if (typeof contenu !== 'object' || contenu === null) throw new OpsSessionError();
    const { odooSessionId, issuedAt } = contenu as Record<string, unknown>;
    if (typeof odooSessionId !== 'string' || odooSessionId.length === 0) {
      throw new OpsSessionError();
    }
    if (typeof issuedAt !== 'number' || !Number.isFinite(issuedAt)) {
      throw new OpsSessionError();
    }
    return { odooSessionId, issuedAt };
  } catch {
    throw new OpsSessionError();
  }
}

export function isExpired(session: OpsSession, maintenant = Date.now()): boolean {
  return maintenant - session.issuedAt >= OPS_SESSION_MAX_AGE_SECONDS * 1000;
}

/**
 * Les attributs du cookie.
 *
 * `httpOnly` : aucun script de la page n'y accède, donc une XSS ne l'exfiltre
 * pas. `sameSite: 'lax'` : il n'accompagne pas les requêtes déclenchées par un
 * autre site. Pas de `domain` : le cookie reste sur `ops.dallytrading.com` et
 * n'est jamais transmis à `dallytrading.com` ni à `crm.dallytrading.com`.
 */
export function cookieOptions(estHttps = opsUsesHttps()) {
  return {
    httpOnly: true,
    secure: estHttps,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: OPS_SESSION_MAX_AGE_SECONDS,
  };
}
