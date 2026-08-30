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
 *
 * Les majuscules sont admises depuis que les références de dossier
 * (`AIR-DSS-CDG-2026-002`) composent un segment. Le point, l'espace, le `%` et
 * le `?` restent exclus : ni remontée de répertoire, ni chaîne de requête
 * glissée dans un segment.
 */
const RESSOURCE_OPS =
  /^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*(?:\/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)*$/;

export class OpsGatewayError extends Error {
  readonly code:
    | 'invalid_credentials'
    | 'forbidden'
    | 'unavailable'
    | 'invalid_path'
    /** Odoo a refusé la *forme* de la demande. Jamais son contenu. */
    | 'invalid_request'
    /** La demande est bien formée, mais la base dit autre chose. */
    | 'not_found'
    | 'conflict'
    /**
     * La demande est bien formée et le contenu est refusé : une date future,
     * une devise absente, un fichier qui n'est pas une photo. Distinct de
     * `invalid_request`, qui dit que la *forme* ne va pas, et distinct de
     * `unavailable`, qui laisserait croire à une panne alors que la saisie est
     * simplement à corriger.
     */
    | 'unprocessable';

  /**
   * Le code stable du refus, tel qu'Odoo l'a nommé.
   *
   * Il voyage jusqu'à l'interface parce que chaque refus appelle un geste
   * différent : « demandez une vérification au responsable » d'un côté,
   * « reprenez la photo » de l'autre. Porté par les conflits comme par les
   * contenus refusés.
   */
  readonly conflictCode?: string;

  constructor(code: OpsGatewayError['code'], message?: string, conflictCode?: string) {
    super(message ?? code);
    this.name = 'OpsGatewayError';
    this.code = code;
    if (conflictCode !== undefined) this.conflictCode = conflictCode;
  }
}

export interface OpsIdentity {
  /**
   * L'opérateur, nommé — jamais numéroté.
   *
   * La clé primaire Odoo ne descend pas jusqu'au navigateur : elle n'y sert à
   * rien, et un identifiant de base publié finit toujours par être utilisé
   * pour désigner quelqu'un.
   */
  readonly user: { readonly name: string; readonly login: string };
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
  readonly methode: 'GET' | 'POST' | 'PUT';
  readonly corps?: unknown;
  /**
   * Un envoi de fichier, quand il y en a un.
   *
   * Séparé de `corps` parce qu'il change le type de contenu : c'est `fetch`
   * qui pose l'en-tête `multipart/form-data`, avec la frontière qu'il a
   * choisie. L'écrire nous-mêmes produirait un corps illisible.
   */
  readonly formulaire?: FormData;
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
  const { chemin, methode, corps, formulaire, sessionId, correlationId } = options;
  if (!cheminAutorise(chemin)) {
    throw new OpsGatewayError('invalid_path', `chemin non autorisé : ${chemin}`);
  }

  const env = opsEnv();
  const enTetes: Record<string, string> = { 'X-Request-ID': correlationId };
  if (formulaire === undefined) enTetes['Content-Type'] = 'application/json';
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
  if (formulaire !== undefined) init.body = formulaire;
  else if (corps !== undefined) init.body = JSON.stringify(corps);

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
 * La réponse d'Odoo, traduite en une erreur ou une charge utile.
 *
 * Un seul endroit pour cette traduction : trois copies divergeraient au premier
 * code d'erreur ajouté, et c'est ici que se décide ce que l'opérateur finit
 * par lire.
 */
async function lireReponse<T>(reponse: Response): Promise<T> {
  if (reponse.status === 403) throw new OpsGatewayError('forbidden');
  // 3xx : Odoo redirige vers /web/login, donc la session n'est plus valide.
  if (reponse.status >= 300 && reponse.status < 400) throw new OpsGatewayError('forbidden');
  if (reponse.status === 404) {
    const charge = (await reponse.json().catch(() => null)) as
      | { error?: { code?: string } }
      | null;
    throw new OpsGatewayError('not_found', 'introuvable', charge?.error?.code);
  }
  if (reponse.status === 400) throw new OpsGatewayError('invalid_request');
  if (reponse.status === 422) {
    // Le contenu est refusé, pas la forme. Sans ce cas, une date future ou une
    // photo illisible remontait en « service indisponible » : l'opérateur
    // aurait attendu au lieu de corriger.
    const charge = (await reponse.json().catch(() => null)) as
      | { error?: { code?: string } }
      | null;
    throw new OpsGatewayError('unprocessable', 'contenu refusé', charge?.error?.code);
  }
  if (reponse.status === 409) {
    // Le code du conflit est relayé ; son message, non : il vient d'Odoo et
    // c'est le BFF qui décide de ce que l'opérateur lit.
    const charge = (await reponse.json().catch(() => null)) as
      | { error?: { code?: string } }
      | null;
    throw new OpsGatewayError('conflict', 'conflit', charge?.error?.code);
  }
  if (!reponse.ok) throw new OpsGatewayError('unavailable', `statut ${reponse.status}`);

  const charge = (await reponse.json()) as { success?: boolean; data?: unknown };
  if (!charge.success || charge.data === undefined) {
    throw new OpsGatewayError('unavailable', 'réponse illisible');
  }
  return charge.data as T;
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

  // La même traduction que partout ailleurs. Cette fonction en portait sa
  // propre copie, plus courte : un dossier introuvable y devenait « service
  // indisponible », si bien que l'écran invitait à patienter au lieu de dire
  // que la référence n'existe pas.
  return lireReponse<T>(reponse);
}

/**
 * Lit un document Ops — un PDF, aujourd'hui le reçu client.
 *
 * Ne renvoie que des octets et un type : jamais un chemin, jamais une URL que
 * le navigateur pourrait rappeler seul. Le document reste derrière la session,
 * comme le reste.
 */
export async function opsGetDocument(
  ressource: string,
  sessionId: string,
  correlationId: string,
): Promise<{ readonly contenu: ArrayBuffer; readonly type: string }> {
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
  if (reponse.status === 404) {
    const charge = (await reponse.json().catch(() => null)) as
      | { error?: { code?: string } }
      | null;
    throw new OpsGatewayError('not_found', 'introuvable', charge?.error?.code);
  }
  if (reponse.status === 409) {
    const charge = (await reponse.json().catch(() => null)) as
      | { error?: { code?: string } }
      | null;
    throw new OpsGatewayError('conflict', 'conflit', charge?.error?.code);
  }
  if (!reponse.ok) throw new OpsGatewayError('unavailable', `statut ${reponse.status}`);

  const type = reponse.headers.get('content-type') ?? '';
  // Odoo répond en JSON quand il refuse ; un refus servi tel quel sous
  // l'étiquette PDF donnerait au client un fichier illisible au lieu d'un
  // message.
  if (!type.toLowerCase().startsWith('application/pdf')) {
    throw new OpsGatewayError('unavailable', 'document inattendu');
  }
  const contenu = await reponse.arrayBuffer();
  if (contenu.byteLength === 0) {
    throw new OpsGatewayError('unavailable', 'document vide');
  }
  return { contenu, type: 'application/pdf' };
}

/** Lecture Ops avec paramètres encodés, sans permettre à l'appelant d'écrire un chemin. */
export async function opsGetQuery<T>(
  ressource: string,
  query: Readonly<Record<string, string>>,
  sessionId: string,
  correlationId: string,
): Promise<T> {
  if (!RESSOURCE_OPS.test(ressource)) {
    throw new OpsGatewayError('invalid_path', `ressource non autorisée : ${ressource}`);
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(key)) {
      throw new OpsGatewayError('invalid_path', 'paramètre non autorisé');
    }
    params.set(key, value);
  }
  const reponse = await appel({
    chemin: `${PREFIXE_OPS}${ressource}?${params.toString()}`,
    methode: 'GET',
    sessionId,
    correlationId,
  });
  return lireReponse<T>(reponse);
}

/**
 * Soumet une demande à une ressource Ops.
 *
 * Existe pour une seule raison : certains arguments de lecture ne doivent pas
 * voyager dans une URL. Un numéro de téléphone placé en chaîne de requête se
 * retrouve dans l'historique du navigateur, dans les journaux du proxy et dans
 * les en-têtes `Referer` — des endroits qui n'ont ni le chiffrement ni la
 * discipline de la base. Le corps d'une requête ne va nulle part de tout cela.
 *
 * Le nom de ressource obéit à la même règle que `opsGet` : c'est un nom, pas
 * un chemin.
 */
export async function opsPost<T>(
  ressource: string,
  corps: unknown,
  sessionId: string,
  correlationId: string,
): Promise<T> {
  if (!RESSOURCE_OPS.test(ressource)) {
    throw new OpsGatewayError('invalid_path', `ressource non autorisée : ${ressource}`);
  }

  const reponse = await appel({
    chemin: `${PREFIXE_OPS}${ressource}`,
    methode: 'POST',
    corps,
    sessionId,
    correlationId,
  });

  return lireReponse<T>(reponse);
}

/**
 * Remplace une ressource Ops.
 *
 * `PUT` parce que le corps décrit l'article entier, pas un delta : deux envois
 * identiques laissent le même état.
 */
export async function opsPut<T>(
  ressource: string,
  corps: unknown,
  sessionId: string,
  correlationId: string,
): Promise<T> {
  if (!RESSOURCE_OPS.test(ressource)) {
    throw new OpsGatewayError('invalid_path', `ressource non autorisée : ${ressource}`);
  }

  const reponse = await appel({
    chemin: `${PREFIXE_OPS}${ressource}`,
    methode: 'PUT',
    corps,
    sessionId,
    correlationId,
  });
  return lireReponse<T>(reponse);
}

/**
 * Dépose un fichier sur une ressource Ops.
 *
 * ## Pourquoi le fichier ne devient pas du JSON
 *
 * Encoder une photo en base64 la fait grossir d'un tiers et oblige les deux
 * bouts à en tenir une copie entière en mémoire. Sur un téléphone au bord du
 * réseau, ce tiers se paie en secondes et parfois en coupure.
 *
 * ## Ce que l'appelant peut et ne peut pas décider
 *
 * Il fournit des octets, un nom, un type annoncé et des champs de texte. Il ne
 * fournit ni en-tête, ni chemin : le nom de ressource obéit à la même règle
 * que partout ailleurs dans ce module. Le type annoncé est transmis tel quel
 * *et n'est pas cru* — c'est Odoo qui tranche, à partir des octets.
 */
export async function opsPostFichier<T>(
  ressource: string,
  fichier: { readonly nom: string; readonly type: string; readonly contenu: Blob },
  champs: Readonly<Record<string, string>>,
  sessionId: string,
  correlationId: string,
): Promise<T> {
  if (!RESSOURCE_OPS.test(ressource)) {
    throw new OpsGatewayError('invalid_path', `ressource non autorisée : ${ressource}`);
  }

  const formulaire = new FormData();
  for (const [cle, valeur] of Object.entries(champs)) formulaire.append(cle, valeur);
  formulaire.append(
    'receipt',
    new File([fichier.contenu], fichier.nom, { type: fichier.type }),
  );

  const reponse = await appel({
    chemin: `${PREFIXE_OPS}${ressource}`,
    methode: 'POST',
    formulaire,
    sessionId,
    correlationId,
  });
  return lireReponse<T>(reponse);
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
