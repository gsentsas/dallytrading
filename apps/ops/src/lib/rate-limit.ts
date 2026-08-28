/**
 * Limitation de débit en mémoire pour la connexion des opérateurs.
 *
 * Même patron que celui du portail client, compteurs délibérément séparés :
 * les deux applications tournent dans des processus distincts, et un client
 * qui martèle le portail ne doit pas verrouiller un logisticien devant un
 * camion à décharger.
 *
 * Portée, dite franchement : les compteurs vivent dans la mémoire d'un seul
 * processus Node. Ils repartent de zéro à chaque redémarrage et ne se
 * coordonnent pas entre instances. C'est une première barrière contre le
 * bourrinage d'un mot de passe, pas une protection volumétrique — celle-ci
 * appartient au proxy inverse.
 */

interface Compteur {
  nombre: number;
  /** Horodatage (ms) de réouverture de la fenêtre. */
  reouvertureA: number;
}

const compteurs = new Map<string, Compteur>();

/** Plafond de clés suivies, pour que la table ne croisse pas sans fin. */
const MAX_CLES = 10_000;

export interface RateLimitResult {
  readonly allowed: boolean;
  readonly remaining: number;
  /** Secondes avant réouverture, utilisable tel quel dans `Retry-After`. */
  readonly retryAfterSeconds: number;
}

/**
 * Consulte un budget sans le consommer.
 *
 * Sert à refuser tôt une requête déjà hors budget, sans faire monter le
 * compteur d'un cran à chaque refus — sinon une fenêtre de cinq minutes se
 * prolongerait indéfiniment sous le martèlement qu'elle est censée arrêter.
 */
export function peekRateLimit(key: string, limit: number): RateLimitResult {
  const maintenant = Date.now();
  const compteur = compteurs.get(key);
  if (!compteur || compteur.reouvertureA <= maintenant) {
    return { allowed: true, remaining: limit, retryAfterSeconds: 0 };
  }
  if (compteur.nombre >= limit) {
    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(1, Math.ceil((compteur.reouvertureA - maintenant) / 1000)),
    };
  }
  return { allowed: true, remaining: limit - compteur.nombre, retryAfterSeconds: 0 };
}

/** Efface un budget. Utilisé après une authentification réussie. */
export function clearRateLimitKey(key: string): void {
  compteurs.delete(key);
}

export function checkRateLimit(key: string, limit: number, windowMs: number): RateLimitResult {
  const maintenant = Date.now();

  if (compteurs.size > MAX_CLES) {
    for (const [cle, compteur] of compteurs) {
      if (compteur.reouvertureA <= maintenant) compteurs.delete(cle);
    }
    if (compteurs.size > MAX_CLES) compteurs.clear();
  }

  const compteur = compteurs.get(key);

  if (!compteur || compteur.reouvertureA <= maintenant) {
    compteurs.set(key, { nombre: 1, reouvertureA: maintenant + windowMs });
    return { allowed: true, remaining: limit - 1, retryAfterSeconds: 0 };
  }

  if (compteur.nombre >= limit) {
    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(1, Math.ceil((compteur.reouvertureA - maintenant) / 1000)),
    };
  }

  compteur.nombre += 1;
  return { allowed: true, remaining: limit - compteur.nombre, retryAfterSeconds: 0 };
}

/**
 * Adresse du client, au mieux.
 *
 * Lue dans `X-Forwarded-For`, que le proxy inverse réécrit. Sans ce proxy
 * devant, l'en-tête serait fourni par l'appelant et la limite contournable
 * d'une ligne.
 */
export function getClientIp(headers: Headers): string {
  const transmise = headers.get('x-forwarded-for');
  if (transmise) {
    const premiere = transmise.split(',')[0]?.trim();
    if (premiere) return premiere;
  }
  return headers.get('x-real-ip')?.trim() ?? 'unknown';
}

/**
 * Les deux budgets de la connexion Ops.
 *
 * Les deux comptent des **échecs**, jamais des réussites.
 *
 * C'est une conséquence directe du terrain : tous les téléphones d'un
 * entrepôt sortent par la même adresse publique. Compter les requêtes
 * verrouillerait l'équipe entière au milieu d'une journée de travail, pour la
 * seule raison qu'elle travaille. Compter les échecs ne se déclenche que
 * lorsqu'il se passe quelque chose d'anormal — et se relâche tout seul.
 *
 * - **L'adresse** arrête un balayage de mots de passe étalé sur plusieurs
 *   comptes depuis un même point de sortie.
 * - **Le compte** arrête l'acharnement sur un opérateur précis, y compris
 *   réparti sur plusieurs adresses. Un logisticien qui se trompe six fois en
 *   cinq minutes n'est plus en train de se tromper.
 *
 * La protection volumétrique, elle, n'est pas ici : elle appartient au proxy
 * inverse, qui voit passer le trafic avant Node.
 *
 * Les préfixes sont explicites (`ops:`) pour qu'aucune clé ne puisse
 * accidentellement croiser celles du portail si les deux tables se
 * retrouvaient un jour dans un magasin partagé.
 */
export const OPS_LOGIN_IP = { limite: 30, fenetreMs: 5 * 60_000 } as const;
export const OPS_LOGIN_UTILISATEUR = { limite: 6, fenetreMs: 5 * 60_000 } as const;

export function cleLoginIp(ip: string): string {
  return `ops:login:ip:${ip}`;
}

/**
 * L'identifiant est normalisé (minuscules, sans espaces) pour que
 * `Gilles`, `gilles` et ` gilles ` partagent le même budget — sinon la
 * limite par compte se contourne en changeant la casse.
 */
export function cleLoginUtilisateur(login: string): string {
  return `ops:login:user:${login.trim().toLowerCase()}`;
}

/** Remet les compteurs à zéro. Réservé aux tests. */
export function resetRateLimits(): void {
  compteurs.clear();
}
