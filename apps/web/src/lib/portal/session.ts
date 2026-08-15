/**
 * Le cookie de session du portail : sceller, ouvrir, détruire.
 *
 * ## Ce que le cookie contient, et pourquoi si peu
 *
 * Uniquement l'identifiant de session Odoo et deux horodatages. Ni e-mail, ni nom,
 * ni `partner_id`, ni groupes, ni rien de métier.
 *
 * La raison n'est pas la taille : c'est qu'une valeur portée par le cookie devient
 * une valeur à laquelle on est tenté de faire confiance. Un `partner_id` scellé
 * serait authentique — et pourtant s'en servir pour filtrer des données
 * transformerait un artefact de transport en autorisation. Comme il n'y a rien
 * d'autre dedans, la seule chose qu'on puisse en faire est de retrouver la session
 * Odoo et de laisser Odoo décider.
 *
 * ## Chiffré, pas seulement signé
 *
 * Un cookie signé est lisible : l'identifiant de session Odoo y serait en clair,
 * visible dans les outils du navigateur, dans un cache disque, dans un rapport de
 * bug. AES-256-GCM le chiffre **et** l'authentifie : modifier un seul octet fait
 * échouer la vérification du tag, et l'ouverture échoue au lieu de renvoyer des
 * données altérées.
 *
 * `node:crypto` suffit — aucune dépendance ajoutée pour cela.
 */

import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  createHash,
} from 'node:crypto';

/** Nom dédié : jamais `session_id`, qui laisserait croire au cookie d'Odoo. */
export const PORTAL_COOKIE = 'dt_portal_session';

/** Durée de vie du cookie. Odoo reste seul juge de la validité réelle. */
export const PORTAL_SESSION_MAX_AGE_SECONDS = 60 * 60 * 8;

const ALGORITHM = 'aes-256-gcm';
const IV_BYTES = 12;
const TAG_BYTES = 16;
const VERSION = 'v1';

/** Ce que le cookie transporte. Volontairement minimal — voir l'en-tête. */
export interface PortalSession {
  /** Identifiant de session Odoo. Le seul secret réel du paquet. */
  readonly odooSessionId: string;
  /** Émission, en secondes epoch. Sert à borner la durée côté BFF. */
  readonly issuedAt: number;
}

export class PortalSessionError extends Error {}

/**
 * Dérive une clé de 32 octets depuis le secret de configuration.
 *
 * SHA-256 plutôt qu'un KDF lent : le secret est déjà un aléa de haute entropie
 * fourni par la configuration, pas un mot de passe humain. Un PBKDF2 coûterait à
 * chaque requête sans rien renforcer.
 */
function keyFrom(secret: string): Buffer {
  return createHash('sha256').update(secret, 'utf8').digest();
}

/** Scelle une session. Le résultat est opaque et infalsifiable. */
export function sealSession(session: PortalSession, secret: string): string {
  const key = keyFrom(secret);
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALGORITHM, key, iv);
  const payload = Buffer.from(JSON.stringify(session), 'utf8');
  const encrypted = Buffer.concat([cipher.update(payload), cipher.final()]);
  const tag = cipher.getAuthTag();
  return [
    VERSION,
    iv.toString('base64url'),
    encrypted.toString('base64url'),
    tag.toString('base64url'),
  ].join('.');
}

/**
 * Ouvre un cookie scellé, ou échoue.
 *
 * Toute anomalie — version inconnue, structure invalide, tag qui ne correspond
 * pas, JSON illisible, champ manquant — produit la même erreur. Distinguer
 * « altéré » de « expiré » n'apprendrait rien d'utile au serveur et donnerait un
 * signal à qui teste des variantes.
 */
export function unsealSession(sealed: string, secret: string): PortalSession {
  const parts = sealed.split('.');
  if (parts.length !== 4 || parts[0] !== VERSION) {
    throw new PortalSessionError('invalid session cookie');
  }
  const [, ivPart, dataPart, tagPart] = parts;
  try {
    const iv = Buffer.from(ivPart as string, 'base64url');
    const data = Buffer.from(dataPart as string, 'base64url');
    const tag = Buffer.from(tagPart as string, 'base64url');
    if (iv.length !== IV_BYTES || tag.length !== TAG_BYTES) {
      throw new PortalSessionError('invalid session cookie');
    }
    const decipher = createDecipheriv(ALGORITHM, keyFrom(secret), iv);
    decipher.setAuthTag(tag);
    const opened = Buffer.concat([decipher.update(data), decipher.final()]);
    const parsed = JSON.parse(opened.toString('utf8')) as Partial<PortalSession>;
    if (
      typeof parsed.odooSessionId !== 'string' ||
      parsed.odooSessionId.length === 0 ||
      typeof parsed.issuedAt !== 'number'
    ) {
      throw new PortalSessionError('invalid session cookie');
    }
    return { odooSessionId: parsed.odooSessionId, issuedAt: parsed.issuedAt };
  } catch (error) {
    if (error instanceof PortalSessionError) throw error;
    throw new PortalSessionError('invalid session cookie');
  }
}

/**
 * La session a-t-elle dépassé la durée que le BFF accepte ?
 *
 * Ce n'est qu'un plafond local. Odoo reste seul juge : une session révoquée de son
 * côté est refusée même si ce contrôle passe. L'inverse serait dangereux — un
 * cookie « encore valide » ne prouve rien sur l'état réel du compte.
 */
export function isExpired(session: PortalSession, now = Date.now()): boolean {
  const age = Math.floor(now / 1000) - session.issuedAt;
  return age < 0 || age > PORTAL_SESSION_MAX_AGE_SECONDS;
}

/** Options du cookie. `secure` seulement hors développement local. */
export function cookieOptions(isProduction: boolean) {
  return {
    httpOnly: true,
    secure: isProduction,
    // Lax et non Strict : une redirection depuis un e-mail d'invitation vers
    // /espace-client doit conserver la session, sinon le client atterrit sur la
    // page de connexion sans comprendre pourquoi. Lax couvre le CSRF sur les
    // requêtes non sûres, qui sont de toute façon protégées par le contrôle
    // d'Origin.
    sameSite: 'lax' as const,
    path: '/',
    maxAge: PORTAL_SESSION_MAX_AGE_SECONDS,
  };
}
