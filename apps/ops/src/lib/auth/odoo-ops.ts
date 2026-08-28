/**
 * La passerelle Ops vers Odoo.
 *
 * ## Une passerelle qui ne peut pas s'authentifier autrement qu'en opérateur
 *
 * Trois contraintes structurelles, et non trois commentaires :
 *
 * 1. **Aucune clé n'est lisible depuis ce module.** La configuration est prise
 *    dans `opsEnv()`, dont le schéma ne comporte ni `DALLY_FREIGHT_SYNC_API_KEY`,
 *    ni `DALLY_FREIGHT_BILLING_API_KEY`, ni `ODOO_API_KEY`. Ces valeurs
 *    n'existent tout simplement pas sur l'objet typé ; les atteindre
 *    demanderait d'écrire `process.env` ici, ce qu'un test refuse.
 * 2. **Les en-têtes ne sont pas paramétrables.** `appel()` les construit
 *    lui-même à partir d'une liste fermée. Aucune fonction publique n'accepte
 *    d'en-têtes : il n'y a pas d'endroit où glisser un `Authorization`.
 * 3. **Les chemins sont sur liste blanche.** Seules la session Odoo et la
 *    famille `/api/v1/ops/` sont joignables. Un appel à `/api/v1/freight/...`
 *    échoue avant même de partir, quelle que soit l'intention de l'appelant.
 *
 * Ce que la passerelle transporte, c'est la session de l'opérateur connecté —
 * rien d'autre. Les droits appliqués sont donc exactement ceux de son compte
 * Odoo, jamais ceux d'une intégration privilégiée.
 */

import { opsEnv } from '@/lib/env';
import { logger } from '@/lib/logger';

/** Chemins joignables. Toute autre cible est refusée avant l'émission. */
const CHEMINS_AUTORISES = [
  '/web/session/authenticate',
  '/web/session/destroy',
  '/api/v1/ops/',
] as const;

/** Préfixe des ressources métier. Il n'est jamais fourni par l'appelant. */
const PREFIXE_OPS = '/api/v1/ops/';

/**
 * Forme d'un nom de ressource.
 *
 * `opsGet` ne prend pas un chemin mais un nom — `consolidations`, et non
 * `/api/v1/ops/consolidations`. Le préfixe est ajouté ici, ce qui rend la
 * sortie du périmètre Ops impossible à écrire plutôt qu'interdite par un
 * contrôle. Le motif exclut le point, donc `../freight/...` ne passe pas.
 */
const RESSOURCE_OPS = /^[a-z0-9]+(?:-[a-z0-9]+)*(?:\/[a-z0-9]+(?:-[a-z0-9]+)*)*$/;

export class OpsGatewayError extends Error {
  readonly code: 'invalid_credentials' | 'forbidden' | 'unavailable' | 'invalid_path';

  constructor(code: OpsGatewayError['code'], message?: string) {
    super(message ?? code);
    this.name = 'OpsGatewayError';
    this.code = code;
  }
}

export interface OpsIdentity {
  readonly user: { readonly id: number; readonly name: string; readonly login: string };
  readonly role: 'logistician' | 'supervisor';
  readonly cash_actor: string | null;
  readonly cash_actor_configured: boolean;
  readonly capabilities: Readonly<Record<string, boolean>>;
}

function cheminAutorise(chemin: string): boolean {
  return CHEMINS_AUTORISES.some((autorise) =>
    autorise.endsWith('/') ? chemin.startsWith(autorise) : chemin === autorise,
  );
}

/**
 * Un identifiant de session sûr à placer dans un en-tête.
 *
 * Odoo produit des jetons alphanumériques. Tout caractère hors de ce jeu —
 * saut de ligne, point-virgule — permettrait d'injecter un second en-tête ;
 * on le refuse plutôt que de l'échapper.
 */
function sessionIdSur(sessionId: string): string {
  if (!/^[A-Za-z0-9._-]{1,512}$/.test(sessionId)) {
    throw new OpsGatewayError('unavailable', 'identifiant de session invalide');
  }
  return sessionId;
}

interface OptionsAppel {
  readonly chemin: string;
  readonly methode: 'GET' | 'POST';
  readonly corps?: unknown;
  /** Session de l'opérateur, quand il y en a une. */
  readonly sessionId?: string;
  readonly correlationId: string;
}

/**
 * L'unique sortie réseau du module.
 *
 * Le journal ne retient que la corrélation, le chemin, la durée et le statut :
 * ni cookie, ni corps, ni mot de passe. Une requête qui échoue doit être
 * traçable sans être rejouable.
 */
async function appel(options: OptionsAppel): Promise<Response> {
  const { chemin, methode, corps, sessionId, correlationId } = options;
  if (!cheminAutorise(chemin)) {
    throw new OpsGatewayError('invalid_path', `chemin non autorisé : ${chemin}`);
  }

  const env = opsEnv();
  const enTetes: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Request-ID': correlationId,
  };
  if (sessionId) {
    enTetes.Cookie = `session_id=${sessionIdSur(sessionId)}`;
  }

  const minuteur = new AbortController();
  const echeance = setTimeout(() => minuteur.abort(), env.ODOO_TIMEOUT_MS);
  const depart = Date.now();

  const init: RequestInit = {
    method: methode,
    headers: enTetes,
    cache: 'no-store',
    // `manual` : une redirection vers /web/login est une réponse, pas une
    // page à suivre. La suivre transformerait un refus en 200.
    redirect: 'manual',
    signal: minuteur.signal,
  };
  if (corps !== undefined) init.body = JSON.stringify(corps);

  try {
    const reponse = await fetch(`${env.ODOO_URL}${chemin}`, init);
    logger.info('odoo.call', {
      correlationId,
      path: chemin,
      status: reponse.status,
      durationMs: Date.now() - depart,
    });
    return reponse;
  } catch (erreur) {
    logger.warn('odoo.call.failed', {
      correlationId,
      path: chemin,
      durationMs: Date.now() - depart,
      aborted: erreur instanceof Error && erreur.name === 'AbortError',
    });
    throw new OpsGatewayError('unavailable', 'Odoo injoignable');
  } finally {
    clearTimeout(echeance);
  }
}

/** Extrait `session_id` d'un `Set-Cookie`. */
function lireCookieSession(reponse: Response): string | null {
  const cookies = reponse.headers.getSetCookie();
  for (const cookie of cookies) {
    const trouve = /(?:^|;\s*)session_id=([^;]+)/.exec(cookie);
    if (trouve?.[1]) return trouve[1];
  }
  return null;
}

/**
 * Ouvre une session Odoo.
 *
 * Le mot de passe traverse cette fonction et n'y reste pas : il n'est ni
 * journalisé, ni conservé, ni replacé dans le cookie. Identifiant inconnu et
 * mot de passe faux produisent la même erreur `invalid_credentials`, pour ne
 * pas révéler quels comptes existent.
 */
export async function authenticate(
  login: string,
  password: string,
  correlationId: string,
): Promise<string> {
  const env = opsEnv();
  const reponse = await appel({
    chemin: '/web/session/authenticate',
    methode: 'POST',
    corps: {
      jsonrpc: '2.0',
      method: 'call',
      params: { db: env.ODOO_DATABASE, login, password },
    },
    correlationId,
  });

  if (!reponse.ok) throw new OpsGatewayError('unavailable', 'Odoo a refusé la requête');

  const charge = (await reponse.json()) as { error?: unknown; result?: { uid?: number | false } };
  if (charge.error || !charge.result?.uid) {
    throw new OpsGatewayError('invalid_credentials');
  }

  const sessionId = lireCookieSession(reponse);
  if (!sessionId) throw new OpsGatewayError('unavailable', 'session Odoo absente de la réponse');
  return sessionId;
}

/**
 * Lit une ressource Ops.
 *
 * L'appelant nomme la ressource, jamais le chemin. `403` signifie « ce compte
 * existe mais n'est pas un compte Ops » : c'est le verdict d'Odoo, et la seule
 * autorité sur la question. Une redirection dit la même chose autrement — la
 * session n'est plus valide.
 */
export async function opsGet<T>(
  ressource: string,
  sessionId: string,
  correlationId: string,
): Promise<T> {
  if (!RESSOURCE_OPS.test(ressource)) {
    throw new OpsGatewayError('invalid_path', `ressource non autorisée : ${ressource}`);
  }

  const reponse = await appel({
    chemin: `${PREFIXE_OPS}${ressource}`,
    methode: 'GET',
    sessionId,
    correlationId,
  });

  if (reponse.status === 403) throw new OpsGatewayError('forbidden');
  if (reponse.status >= 300 && reponse.status < 400) throw new OpsGatewayError('forbidden');
  if (!reponse.ok) throw new OpsGatewayError('unavailable', `statut ${reponse.status}`);

  const charge = (await reponse.json()) as { success?: boolean; data?: unknown };
  if (!charge.success || charge.data === undefined) {
    throw new OpsGatewayError('unavailable', 'réponse illisible');
  }
  return charge.data as T;
}

/** L'identité de l'opérateur connecté. */
export function fetchIdentity(sessionId: string, correlationId: string): Promise<OpsIdentity> {
  return opsGet<OpsIdentity>('me', sessionId, correlationId);
}

/**
 * Ferme la session Odoo.
 *
 * Sans effet visible en cas d'échec : la déconnexion locale ne doit jamais
 * être empêchée par un Odoo indisponible, sinon un opérateur reste connecté
 * sur un terminal partagé.
 */
export async function destroySession(sessionId: string, correlationId: string): Promise<void> {
  try {
    await appel({
      chemin: '/web/session/destroy',
      methode: 'POST',
      corps: { jsonrpc: '2.0', method: 'call', params: {} },
      sessionId,
      correlationId,
    });
  } catch {
    logger.warn('odoo.destroy.failed', { correlationId });
  }
}
