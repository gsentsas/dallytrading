/**
 * Data Access Layer du portail : le seul endroit qui sait lire une session.
 *
 * Toute page privée et tout Route Handler passent par ici. Dupliquer la lecture du
 * cookie dans chaque fichier finirait par produire une variante qui oublie de
 * vérifier l'expiration, et cette variante-là serait la faille.
 *
 * ## La règle qui gouverne ce fichier
 *
 * Un cookie valide ne prouve rien d'autre que « une session Odoo existait ». Il ne
 * dit pas si elle est encore active, si le compte a été désactivé, ni ce que
 * l'utilisateur a le droit de voir. Chaque accès privé repose donc sur un appel
 * réel à Odoo — c'est Odoo qui répond, et son refus fait foi.
 */

import { cookies } from 'next/headers';

import { getServerEnv } from '@/lib/env';
import {
  PORTAL_COOKIE,
  PortalSessionError,
  cookieOptions,
  isExpired,
  sealSession,
  unsealSession,
  type PortalSession,
} from './session';
import {
  PortalGatewayError,
  PortalOdooGateway,
  type PortalIdentity,
} from './odoo-portal';

/** Lit et ouvre le cookie, ou renvoie `null`. Ne lève jamais. */
export async function readPortalSession(): Promise<PortalSession | null> {
  const secret = getServerEnv().PORTAL_SESSION_SECRET;
  const store = await cookies();
  const raw = store.get(PORTAL_COOKIE)?.value;
  if (!raw) return null;
  try {
    const session = unsealSession(raw, secret);
    // Plafond local. Odoo reste juge, mais inutile de l'interroger avec une
    // session que nous savons déjà périmée.
    return isExpired(session) ? null : session;
  } catch (error) {
    if (error instanceof PortalSessionError) return null;
    return null;
  }
}

/**
 * Le cookie doit-il porter `Secure` ?
 *
 * Dérivé du schéma de `NEXT_PUBLIC_SITE_URL`, et non d'une variable
 * `ENVIRONMENT` : celle-ci a un défaut `development` et est absente de
 * `apps/web/.env.production`, le fichier que systemd charge réellement. S'y fier
 * aurait retiré `Secure` en production sans qu'aucune erreur ne le signale — et
 * un cookie de session sans `Secure` part en clair à la première requête http://.
 *
 * Le schéma de l'URL du site est exactement la condition sous laquelle un cookie
 * `Secure` fonctionne : en https il est requis, en http local il empêcherait la
 * connexion. Il ne peut pas se désynchroniser de la réalité.
 */
function wantsSecureCookie(): boolean {
  return getServerEnv().NEXT_PUBLIC_SITE_URL.startsWith('https://');
}

/** Écrit le cookie scellé. */
export async function writePortalSession(odooSessionId: string): Promise<void> {
  const session: PortalSession = {
    odooSessionId,
    issuedAt: Math.floor(Date.now() / 1000),
  };
  const store = await cookies();
  store.set(
    PORTAL_COOKIE,
    sealSession(session, getServerEnv().PORTAL_SESSION_SECRET),
    cookieOptions(wantsSecureCookie()),
  );
}

/** Supprime le cookie. Idempotent. */
export async function clearPortalSession(): Promise<void> {
  const store = await cookies();
  store.set(PORTAL_COOKIE, '', {
    ...cookieOptions(wantsSecureCookie()),
    maxAge: 0,
  });
}

export const portalGateway = new PortalOdooGateway();

/**
 * L'identité du client, telle qu'Odoo la renvoie — jamais reconstruite localement.
 *
 * Renvoie `null` dès qu'Odoo refuse la session : expirée, révoquée, ou compte
 * désactivé. L'appelant n'a pas à distinguer ces cas, il n'affiche rien.
 */
export async function getPortalMe(
  correlationId: string,
): Promise<PortalIdentity | null> {
  const session = await readPortalSession();
  if (!session) return null;
  try {
    return await portalGateway.get<PortalIdentity>(
      '/me', session.odooSessionId, correlationId,
    );
  } catch (error) {
    if (
      error instanceof PortalGatewayError &&
      (error.code === 'unauthenticated' || error.code === 'forbidden')
    ) {
      return null;
    }
    // Odoo injoignable : on ne peut pas conclure que la session est valide, donc
    // on ne laisse pas passer. Propagé pour que l'appelant réponde 503 plutôt
    // qu'une page vide.
    throw error;
  }
}

/**
 * Exige une session vérifiée auprès d'Odoo, sinon lève.
 *
 * C'est ce que les Server Components appellent. Le proxy a peut-être laissé
 * passer sur la seule présence d'un cookie ; ici, la vérification est réelle.
 */
export async function requirePortalSession(
  correlationId: string,
): Promise<PortalIdentity> {
  const identity = await getPortalMe(correlationId);
  if (!identity) {
    throw new PortalGatewayError('unauthenticated', 'no valid portal session');
  }
  return identity;
}

/**
 * Connexion : authentifie auprès d'Odoo, puis **vérifie ce qu'on a obtenu**.
 *
 * L'étape de vérification n'est pas décorative. `/web/session/authenticate` accepte
 * aussi un salarié : sans le rappel à `/api/v1/portal/me`, un compte interne
 * obtiendrait un cookie portail. L'endpoint Odoo refuse les non-`share` par un 403,
 * ce qui fait de cet appel le contrôle qui décide.
 */
export async function loginPortal(
  login: string,
  password: string,
  correlationId: string,
): Promise<PortalIdentity> {
  const sessionId = await portalGateway.authenticate(
    login, password, correlationId,
  );
  let identity: PortalIdentity;
  try {
    identity = await portalGateway.get<PortalIdentity>(
      '/me', sessionId, correlationId,
    );
  } catch (error) {
    // Session ouverte mais inutilisable pour le portail — typiquement un compte
    // interne. On la referme immédiatement plutôt que de la laisser vivre.
    await portalGateway.destroySession(sessionId, correlationId);
    if (error instanceof PortalGatewayError && error.code !== 'unavailable') {
      throw new PortalGatewayError(
        'invalid_credentials', 'not a portal account',
      );
    }
    throw error;
  }
  await writePortalSession(sessionId);
  return identity;
}

/** Déconnexion : détruit côté Odoo, puis retire le cookie. Idempotent. */
export async function logoutPortal(correlationId: string): Promise<void> {
  const session = await readPortalSession();
  if (session) {
    await portalGateway.destroySession(session.odooSessionId, correlationId);
  }
  await clearPortalSession();
}
