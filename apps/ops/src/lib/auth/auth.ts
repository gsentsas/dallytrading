/**
 * L'orchestration de la connexion des opérateurs.
 *
 * Le navigateur ne parle jamais à Odoo. Il parle à ce serveur, qui détient le
 * cookie scellé, ouvre la session Odoo et relaie. C'est ce qui permet de
 * garantir qu'aucun secret ne descend dans la page : il n'y a rien à
 * descendre.
 */

import { cookies } from 'next/headers';

import {
  OPS_COOKIE,
  OpsSessionError,
  cookieOptions,
  isExpired,
  sealSession,
  unsealSession,
  type OpsSession,
} from '@/lib/auth/session';
import {
  OpsGatewayError,
  authenticate,
  destroySession,
  fetchIdentity,
  type OpsIdentity,
} from '@/lib/auth/odoo-ops';
import { logger } from '@/lib/logger';

/**
 * Le seul message d'échec de connexion.
 *
 * Identifiant inconnu, mot de passe faux, compte sans rôle Ops, compte
 * désactivé : tout produit cette phrase. Distinguer les cas transformerait le
 * formulaire en annuaire des comptes existants et des comptes habilités.
 */
export const MESSAGE_ECHEC_CONNEXION = 'Identifiants invalides.';

export async function readOpsSession(): Promise<OpsSession | null> {
  const magasin = await cookies();
  const brut = magasin.get(OPS_COOKIE)?.value;
  if (!brut) return null;
  try {
    const session = unsealSession(brut);
    return isExpired(session) ? null : session;
  } catch (erreur) {
    if (erreur instanceof OpsSessionError) return null;
    throw erreur;
  }
}

export async function writeOpsSession(session: OpsSession): Promise<void> {
  const magasin = await cookies();
  magasin.set(OPS_COOKIE, sealSession(session), cookieOptions());
}

export async function clearOpsSession(): Promise<void> {
  const magasin = await cookies();
  magasin.set(OPS_COOKIE, '', { ...cookieOptions(), maxAge: 0 });
}

/**
 * Connecte un opérateur.
 *
 * L'ordre des étapes porte la sécurité :
 *
 * 1. ouvrir la session Odoo ;
 * 2. **demander l'identité avant de sceller quoi que ce soit** ;
 * 3. si le compte n'est pas un compte Ops, détruire la session Odoo qui vient
 *    d'être ouverte, puis échouer.
 *
 * Sceller d'abord et vérifier ensuite laisserait, entre les deux, un cookie
 * valide pour un compte non habilité. Détruire la session côté Odoo évite en
 * plus qu'un jeton ouvert traîne après un refus.
 */
export async function loginOps(
  login: string,
  password: string,
  correlationId: string,
): Promise<OpsIdentity> {
  let sessionId: string;
  try {
    sessionId = await authenticate(login, password, correlationId);
  } catch (erreur) {
    if (erreur instanceof OpsGatewayError && erreur.code === 'invalid_credentials') {
      logger.info('ops.login.refused', { correlationId, reason: 'credentials' });
    }
    throw erreur;
  }

  let identite: OpsIdentity;
  try {
    identite = await fetchIdentity(sessionId, correlationId);
  } catch (erreur) {
    await destroySession(sessionId, correlationId);
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      logger.info('ops.login.refused', { correlationId, reason: 'not_ops' });
      throw new OpsGatewayError('invalid_credentials');
    }
    throw erreur;
  }

  await writeOpsSession({ odooSessionId: sessionId, issuedAt: Date.now() });
  logger.info('ops.login.accepted', { correlationId, role: identite.role });
  return identite;
}

/**
 * Déconnecte, sans condition de réussite.
 *
 * Le cookie local est effacé quoi qu'il arrive, y compris s'il était déjà
 * absent ou si Odoo ne répond pas : appeler deux fois donne le même résultat
 * qu'appeler une fois.
 */
export async function logoutOps(correlationId: string): Promise<void> {
  const session = await readOpsSession();
  if (session) {
    await destroySession(session.odooSessionId, correlationId);
  }
  await clearOpsSession();
  logger.info('ops.logout', { correlationId, hadSession: Boolean(session) });
}

/**
 * L'identité courante, relue auprès d'Odoo.
 *
 * Aucune mise en cache : c'est le prix, assumé, du fait qu'un droit retiré
 * dans Odoo s'applique à la requête suivante. Un cookie encore valide dont la
 * session Odoo est morte renvoie `null`, et le cookie est effacé au passage
 * pour ne pas boucler sur une session fantôme.
 */
export async function currentIdentity(correlationId: string): Promise<OpsIdentity | null> {
  const session = await readOpsSession();
  if (!session) return null;
  try {
    return await fetchIdentity(session.odooSessionId, correlationId);
  } catch (erreur) {
    if (erreur instanceof OpsGatewayError && erreur.code === 'forbidden') {
      await clearOpsSession();
      return null;
    }
    throw erreur;
  }
}
