/**
 * La base locale de Dally Ops.
 *
 * ## Pourquoi IndexedDB, et pas `localStorage`
 *
 * `localStorage` est synchrone, plafonné à quelques mégaoctets, et ne stocke
 * que des chaînes. Surtout, il n'a pas de transactions : deux onglets qui
 * écrivent en même temps se recouvrent sans que personne ne le sache. Une
 * file d'opérations de caisse ne peut pas reposer là-dessus.
 *
 * ## Pourquoi aucune librairie
 *
 * Trois magasins, deux index, une migration. Une dépendance apporterait ici
 * plus de surface que de service, et cette base doit rester lisible par
 * quiconque devra la déboguer depuis un téléphone d'entrepôt.
 *
 * ## La migration, et ce qu'elle ne fera jamais
 *
 * Le numéro de version augmente quand la forme change. Une version inconnue —
 * celle d'une PWA plus récente restée en cache, par exemple — ne doit
 * **jamais** faire disparaître la file ni requalifier des opérations en
 * « synchronisé ». Dans le doute, on garde et on signale.
 */

import type { BrouillonLocal, MutationLocale } from '@/lib/offline/types';

export const NOM_BASE = 'dally-ops';

/**
 * La version du schéma local.
 *
 * 1 — magasins initiaux : brouillons, mutations, métadonnées.
 */
export const VERSION_SCHEMA = 1;

export const MAGASIN_BROUILLONS = 'ops_drafts';
export const MAGASIN_MUTATIONS = 'ops_mutations';
export const MAGASIN_META = 'ops_metadata';

/** Ce que le navigateur doit fournir pour que la file existe. */
export function indexedDbDisponible(): boolean {
  return typeof indexedDB !== 'undefined';
}

/**
 * Crée ou met à niveau les magasins.
 *
 * Écrite pour être rejouable depuis n'importe quelle version antérieure :
 * chaque étape teste l'existence de ce qu'elle ajoute plutôt que de supposer
 * l'état précédent.
 */
export function migrer(base: IDBDatabase, ancienne: number): void {
  if (!base.objectStoreNames.contains(MAGASIN_MUTATIONS)) {
    const magasin = base.createObjectStore(MAGASIN_MUTATIONS, { keyPath: 'local_id' });
    magasin.createIndex('par_statut', 'status', { unique: false });
    magasin.createIndex('par_proprietaire', 'owner_key', { unique: false });
    // Un même `request_uuid` ne peut désigner qu'une opération : c'est la
    // garantie locale qui double celle du serveur.
    magasin.createIndex('par_demande', 'request_uuid', { unique: true });
    magasin.createIndex('par_parent', 'parent_local_id', { unique: false });
  }
  if (!base.objectStoreNames.contains(MAGASIN_BROUILLONS)) {
    const magasin = base.createObjectStore(MAGASIN_BROUILLONS, { keyPath: 'local_id' });
    magasin.createIndex('par_proprietaire', 'owner_key', { unique: false });
  }
  if (!base.objectStoreNames.contains(MAGASIN_META)) {
    base.createObjectStore(MAGASIN_META, { keyPath: 'cle' });
  }
  // `ancienne` sert aux migrations destructrices à venir. Aujourd'hui, aucune
  // n'existe — et c'est délibéré : une migration qui réécrit des opérations en
  // attente est le meilleur moyen de perdre de la caisse.
  void ancienne;
}

let ouverture: Promise<IDBDatabase> | null = null;

/** Ouvre la base, une fois, et la garde. */
export function ouvrirBase(): Promise<IDBDatabase> {
  if (!indexedDbDisponible()) {
    return Promise.reject(new Error('IndexedDB indisponible'));
  }
  ouverture ??= new Promise<IDBDatabase>((resoudre, rejeter) => {
    const demande = indexedDB.open(NOM_BASE, VERSION_SCHEMA);
    demande.onupgradeneeded = (evenement) => {
      migrer(demande.result, evenement.oldVersion);
    };
    demande.onsuccess = () => {
      // Une PWA plus récente ouverte dans un autre onglet peut faire monter la
      // version sous nos pieds : on ferme proprement plutôt que de bloquer
      // cette montée, et le prochain appel rouvrira.
      demande.result.onversionchange = () => {
        demande.result.close();
        ouverture = null;
      };
      resoudre(demande.result);
    };
    demande.onerror = () => rejeter(demande.error ?? new Error('IndexedDB'));
    demande.onblocked = () => rejeter(new Error('IndexedDB bloquée'));
  }).catch((erreur) => {
    ouverture = null;
    throw erreur;
  });
  return ouverture;
}

/** Réservé aux tests : oublie la base ouverte. */
export function reinitialiserBase(): void {
  ouverture = null;
}

type Mode = 'readonly' | 'readwrite';

/** Exécute une transaction et attend qu'elle soit réellement validée. */
export function transaction<T>(
  magasins: string | string[],
  mode: Mode,
  action: (t: IDBTransaction) => Promise<T> | T,
): Promise<T> {
  return ouvrirBase().then((base) => new Promise<T>((resoudre, rejeter) => {
    const t = base.transaction(magasins, mode);
    let valeur: T;
    let echec: unknown = null;
    // On résout à `oncomplete`, pas au retour de l'action : tant que la
    // transaction n'est pas validée, rien n'est écrit, et annoncer le
    // contraire serait exactement le mensonge que cette file combat.
    t.oncomplete = () => (echec ? rejeter(echec) : resoudre(valeur));
    t.onerror = () => rejeter(t.error ?? echec ?? new Error('transaction'));
    t.onabort = () => rejeter(t.error ?? echec ?? new Error('transaction annulée'));
    Promise.resolve(action(t)).then(
      (resultat) => { valeur = resultat; },
      (erreur) => { echec = erreur; try { t.abort(); } catch { /* déjà close */ } },
    );
  }));
}

/** Emballe une requête IndexedDB en promesse. */
export function requete<T>(demande: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resoudre, rejeter) => {
    demande.onsuccess = () => resoudre(demande.result);
    demande.onerror = () => rejeter(demande.error ?? new Error('requête'));
  });
}

export type EnregistrementLocal = MutationLocale | BrouillonLocal;

/**
 * L'empreinte de l'opérateur de la dernière session ouverte ici.
 *
 * Ce n'est ni un secret, ni un nom : une empreinte, écrite pour que l'écran de
 * synchronisation fonctionne **sans réseau**. Sans elle, la seule façon de
 * savoir à qui appartiennent les opérations locales serait d'interroger le
 * serveur — c'est-à-dire précisément ce qui manque quand on en a besoin.
 */
export const CLE_PROPRIETAIRE_COURANT = 'proprietaire_courant';

export async function ecrireMeta(cle: string, valeur: unknown): Promise<void> {
  await transaction(MAGASIN_META, 'readwrite', (t) =>
    requete(t.objectStore(MAGASIN_META).put({ cle, valeur })));
}

export async function lireMeta<T>(cle: string): Promise<T | null> {
  const ligne = await transaction(MAGASIN_META, 'readonly', (t) =>
    requete<{ cle: string; valeur: T } | undefined>(
      t.objectStore(MAGASIN_META).get(cle)));
  return ligne ? ligne.valeur : null;
}
