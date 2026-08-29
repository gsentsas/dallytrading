/**
 * Le droit de traiter la file, à un seul onglet à la fois.
 *
 * ## Pourquoi
 *
 * Deux onglets Dally Ops ouverts feraient partir deux fois chaque opération.
 * Le serveur les absorberait — l'idempotence est là pour ça — mais le terrain
 * paierait deux fois la latence sur une 4G d'entrepôt, et les journaux
 * deviendraient illisibles.
 *
 * ## Pourquoi un bail, et pas un simple drapeau
 *
 * Un onglet peut disparaître sans prévenir : téléphone verrouillé, navigateur
 * tué, batterie vide. Un drapeau posé resterait posé pour toujours et
 * paralyserait la file. Un bail expire.
 *
 * `navigator.locks` fait cela nativement et libère tout seul quand l'onglet
 * meurt ; là où il manque, le repli sur `localStorage` conserve la propriété
 * essentielle — un seul travailleur — au prix d'une reprise différée après un
 * arrêt brutal.
 *
 * La sûreté finale reste de toute façon assurée par l'idempotence serveur : ce
 * verrou évite du gaspillage, il ne garantit rien de métier.
 */

const CLE_BAIL = 'dally-ops:sync-lease';
const DUREE_BAIL_MS = 30_000;

interface Bail { readonly proprietaire: string; readonly expire_a: number; }

const identiteOnglet = (() => {
  try { return crypto.randomUUID(); } catch { return String(Math.random()); }
})();

function verrousNatifsDisponibles(): boolean {
  return typeof navigator !== 'undefined'
    && typeof (navigator as Navigator & { locks?: unknown }).locks === 'object';
}

function lireBail(): Bail | null {
  try {
    const brut = localStorage.getItem(CLE_BAIL);
    return brut ? JSON.parse(brut) as Bail : null;
  } catch { return null; }
}

/**
 * Exécute `travail` si — et seulement si — cet onglet obtient le bail.
 *
 * Rend `null` sans rien faire quand un autre onglet travaille déjà. Ce n'est
 * pas une erreur : c'est le cas normal, et l'appelant doit simplement passer
 * son tour.
 */
export async function avecBail<T>(travail: () => Promise<T>): Promise<T | null> {
  // Deux appels dans le **même** onglet — deux minuteurs, un clic pendant une
  // reprise automatique — ne sont pas couverts par un bail entre onglets :
  // ils partagent la même identité, et un verrou inter-onglets les laisserait
  // passer tous les deux. Ce drapeau les sérialise à la source.
  if (occupe) return null;
  occupe = true;
  try {
    return await avecBailPartage(travail);
  } finally {
    occupe = false;
  }
}

let occupe = false;

async function avecBailPartage<T>(travail: () => Promise<T>): Promise<T | null> {
  if (verrousNatifsDisponibles()) {
    const locks = (navigator as Navigator & {
      locks: { request: (nom: string, options: object, f: () => Promise<T | null>) => Promise<T | null> };
    }).locks;
    return locks.request(CLE_BAIL, { ifAvailable: true }, async () => travail());
  }

  const instant = Date.now();
  const courant = lireBail();
  if (courant && courant.expire_a > instant && courant.proprietaire !== identiteOnglet) {
    return null;
  }
  try {
    localStorage.setItem(CLE_BAIL, JSON.stringify({
      proprietaire: identiteOnglet, expire_a: instant + DUREE_BAIL_MS,
    }));
  } catch { /* stockage refusé : on travaille sans coordination */ }
  try {
    return await travail();
  } finally {
    try {
      const apres = lireBail();
      if (!apres || apres.proprietaire === identiteOnglet) localStorage.removeItem(CLE_BAIL);
    } catch { /* rien à libérer */ }
  }
}

/** Réservé aux tests. */
export function identiteDeCetOnglet(): string {
  return identiteOnglet;
}
