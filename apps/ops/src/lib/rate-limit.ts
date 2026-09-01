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

import { createHash } from 'node:crypto';

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

/**
 * Les budgets de la recherche client.
 *
 * Ils protègent d'une chose précise : l'énumération automatisée du fichier
 * clients. Un script qui essaierait les numéros les uns après les autres
 * finirait par cartographier la clientèle, un « aucun client trouvé » à la
 * fois.
 *
 * Deux clés, et la session d'abord. Tous les téléphones d'un entrepôt sortent
 * par la même adresse publique : une limite qui ne connaîtrait que l'IP
 * frapperait l'équipe entière pour l'imprudence d'un seul poste. La session
 * cible le poste ; l'adresse reste un plafond large, contre celui qui
 * ouvrirait vingt sessions.
 *
 * Les seuils sont hors d'atteinte d'une réception normale : une réception,
 * c'est une recherche, parfois deux quand le client donne d'abord un mauvais
 * numéro. Soixante en cinq minutes, c'est déjà un poste qui ne réceptionne
 * plus rien.
 */
export const OPS_RECHERCHE_SESSION = { limite: 60, fenetreMs: 5 * 60_000 } as const;
export const OPS_RECHERCHE_IP = { limite: 300, fenetreMs: 5 * 60_000 } as const;

/**
 * La clé d'une session, dérivée et non recopiée.
 *
 * L'identifiant de session Odoo vaut un mot de passe : il ne doit apparaître
 * ni dans une table en mémoire, ni dans un message de journal. On n'en garde
 * qu'une empreinte, tronquée — assez longue pour qu'aucune collision ne
 * survienne à cette échelle, trop courte pour servir à quoi que ce soit
 * d'autre.
 */
export function cleRechercheSession(identifiantSession: string): string {
  const empreinte = createHash('sha256')
    .update(`ops:recherche:${identifiantSession}`, 'utf8')
    .digest('hex')
    .slice(0, 32);
  return `ops:customers:session:${empreinte}`;
}

export function cleRechercheIp(ip: string): string {
  return `ops:customers:ip:${ip}`;
}

/**
 * Les budgets de la création de client.
 *
 * Beaucoup plus bas que ceux de la recherche : créer un client est un geste
 * rare, une fois par nouveau client, tandis qu'on cherche à chaque réception.
 * Une limite basse coûte donc peu au terrain et ferme la porte à qui voudrait
 * peupler le fichier clients depuis un téléphone.
 */
export const OPS_CREATION_SESSION = { limite: 20, fenetreMs: 10 * 60_000 } as const;
export const OPS_CREATION_IP = { limite: 100, fenetreMs: 10 * 60_000 } as const;

export function cleCreationSession(identifiantSession: string): string {
  const empreinte = createHash('sha256')
    .update(`ops:creation:${identifiantSession}`, 'utf8')
    .digest('hex')
    .slice(0, 32);
  return `ops:customers:create:session:${empreinte}`;
}

export function cleCreationIp(ip: string): string {
  return `ops:customers:create:ip:${ip}`;
}

/**
 * La clé qui marque une demande comme déjà comptée.
 *
 * Une 4G capricieuse fait renvoyer la même demande plusieurs fois. Ces
 * tentatives portent le même `request_uuid` et ne produiront qu'une seule
 * fiche : les compter comme vingt créations distinctes punirait l'opérateur
 * pour la qualité du réseau de son entrepôt.
 *
 * L'identifiant est haché ici aussi. Ce n'est pas un secret, mais il n'a rien
 * à faire en clair dans une structure qu'on inspecte au débogage.
 */
export function cleDemandeComptee(requestUuid: string): string {
  const empreinte = createHash('sha256')
    .update(`ops:creation:demande:${requestUuid}`, 'utf8')
    .digest('hex')
    .slice(0, 32);
  return `ops:customers:create:uuid:${empreinte}`;
}

/** Budgets des réceptions et de la liste de familles tarifaires. */
export const OPS_INTAKE_SESSION = {
  limite: 60,
  fenetreMs: 10 * 60_000,
} as const;
export const OPS_INTAKE_IP = {
  limite: 300,
  fenetreMs: 10 * 60_000,
} as const;

function empreinteCourte(namespace: string, valeur: string): string {
  return createHash('sha256')
    .update(`ops:${namespace}:${valeur}`, 'utf8')
    .digest('hex')
    .slice(0, 32);
}

export function cleIntakeSession(
  identifiantSession: string,
): string {
  return `ops:intakes:session:${empreinteCourte(
    'intake', identifiantSession,
  )}`;
}

export function cleIntakeIp(ip: string): string {
  return `ops:intakes:ip:${ip}`;
}

export function cleIntakeDemande(
  requestUuid: string,
): string {
  return `ops:intakes:uuid:${empreinteCourte(
    'intake-request', requestUuid,
  )}`;
}

/**
 * Budgets des envois de justificatifs.
 *
 * Plus serrés que les écritures de texte, et pour une raison matérielle : une
 * photo pèse mille fois plus qu'une ligne de saisie. Un terminal qui en envoie
 * cent à la minute ne travaille pas, il sature. La fenêtre reste large pour
 * qu'une journée de tournée normale — quelques dizaines de tickets — passe
 * sans jamais toucher la limite.
 */
export const OPS_JUSTIFICATIF_SESSION = {
  limite: 40,
  fenetreMs: 10 * 60_000,
} as const;
export const OPS_JUSTIFICATIF_IP = {
  limite: 200,
  fenetreMs: 10 * 60_000,
} as const;

export function cleJustificatifSession(identifiantSession: string): string {
  return `ops:receipts:session:${empreinteCourte('receipt', identifiantSession)}`;
}

export function cleJustificatifIp(ip: string): string {
  return `ops:receipts:ip:${ip}`;
}

/**
 * Budgets des preuves photographiques d'un dossier.
 *
 * Distincts de ceux du justificatif de caisse, et pour une raison de terrain :
 * un opérateur envoie une photo de ticket par dépense, mais documente un colis
 * abîmé sous cinq angles d'affilée. Partager le budget ferait payer au second
 * geste la parcimonie attendue du premier.
 *
 * Plus serrés en revanche que les écritures de texte : une photo pèse mille
 * fois plus qu'une ligne de saisie.
 */
export const OPS_PHOTO_SESSION = {
  limite: 30,
  fenetreMs: 10 * 60_000,
} as const;
export const OPS_PHOTO_IP = {
  limite: 120,
  fenetreMs: 10 * 60_000,
} as const;

export function clePhotoSession(identifiantSession: string): string {
  return `ops:photos:session:${empreinteCourte('photo', identifiantSession)}`;
}

export function clePhotoIp(ip: string): string {
  return `ops:photos:ip:${ip}`;
}

/**
 * Le budget des reprises d'un geste déjà admis.
 *
 * Un rejeu échappe au budget de session — il a déjà payé sa place, et le
 * serveur lui rendra la photo qu'il a écrite. Mais « échapper » ne veut pas
 * dire « sans fin » : cinq reprises suffisent largement à un téléphone qui
 * perd le réseau, et au-delà ce n'est plus une reprise, c'est un martèlement.
 */
export const OPS_PHOTO_REPLAY = {
  limite: 5,
  fenetreMs: 10 * 60_000,
} as const;

/**
 * La clé d'admission d'un geste.
 *
 * Elle ne dit pas « déjà vu » mais **« déjà traité avec succès par Odoo »**.
 * La nuance décide de tout : une clé posée à la simple observation ferait
 * qu'un envoi refusé — par le débit, par une validation, par une panne —
 * deviendrait ensuite un rejeu autorisé à contourner le budget. Elle n'est
 * donc écrite qu'après une réponse serveur réussie.
 */
/**
 * Budget des événements consignés depuis le terrain.
 *
 * Vingt par dix minutes : un opérateur qui documente un colis abîmé en écrit
 * deux ou trois, jamais vingt. Le budget n'existe pas pour le gêner mais pour
 * qu'un appareil devenu fou ne remplisse pas la frise d'un dossier.
 *
 * Plus simple que celui des photos : un événement pèse quelques centaines
 * d'octets, et son rejeu est déjà borné par le registre d'idempotence côté
 * Odoo — qui rend le même événement sans jamais en écrire un second.
 */
export const OPS_EVENT_SESSION = {
  limite: 20,
  fenetreMs: 10 * 60_000,
} as const;
export const OPS_EVENT_IP = {
  limite: 100,
  fenetreMs: 10 * 60_000,
} as const;

export function cleEvenementSession(identifiantSession: string): string {
  return `ops:events:session:${empreinteCourte('event', identifiantSession)}`;
}

export function cleEvenementIp(ip: string): string {
  return `ops:events:ip:${ip}`;
}

/**
 * L'espace de déduplication propre aux événements.
 *
 * `cleDemandeComptee` porte le préfixe `ops:customers:create:` — c'est la clé
 * des créations de client, empruntée par toutes les mutations JSON. Deux
 * gestes de nature différente portant le même `request_uuid` se voleraient
 * donc leur budget : le second se croirait déjà compté et ne consommerait
 * rien, tout en atteignant Odoo. Les événements comptent dans le leur.
 */
export function cleEvenementDemande(requestUuid: string): string {
  return `ops:events:uuid:${empreinteCourte('event-request', requestUuid)}`;
}

export function clePhotoAdmise(requestUuid: string): string {
  return `ops:photos:admis:${empreinteCourte('photo-admis', requestUuid)}`;
}

/** Le compteur de reprises d'un geste admis. */
export function clePhotoRejeu(requestUuid: string): string {
  return `ops:photos:rejeu:${empreinteCourte('photo-rejeu', requestUuid)}`;
}

export function cleJustificatifDemande(requestUuid: string): string {
  return `ops:receipts:uuid:${empreinteCourte('receipt-request', requestUuid)}`;
}

/** Remet les compteurs à zéro. Réservé aux tests. */
export function resetRateLimits(): void {
  compteurs.clear();
}
