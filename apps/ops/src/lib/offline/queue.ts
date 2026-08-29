/**
 * La file des opérations, et les règles qui la gouvernent.
 *
 * ## L'invariant central
 *
 * Une opération ne devient `synced` qu'après une réponse **positive** du
 * serveur. Ni `navigator.onLine`, ni le départ d'un `fetch`, ni la réception
 * de la requête par un Service Worker ne valent confirmation. Toutes les
 * transitions passent par ce fichier, précisément pour qu'il n'existe qu'un
 * seul endroit où cette règle puisse être violée.
 *
 * ## L'identifiant de demande
 *
 * Il est tiré à l'entrée en file — donc **avant** la première tentative
 * réseau — et ne change plus. Aucune fonction de ce module ne permet de le
 * réécrire.
 */

import {
  MAGASIN_BROUILLONS, MAGASIN_MUTATIONS, requete, transaction,
} from '@/lib/offline/db';
import type {
  BrouillonLocal, EtatMutation, MutationLocale, TypeOperation,
} from '@/lib/offline/types';

/** Le délai avant nouvelle tentative, en millisecondes. */
const PALIERS_RETENTE = [0, 5_000, 15_000, 60_000, 300_000, 900_000] as const;

/**
 * Combien de temps une opération synchronisée reste lisible.
 *
 * Assez pour que l'opérateur voie ce qui vient de partir ; pas assez pour
 * qu'un téléphone d'entrepôt devienne une archive de données clients.
 */
export const RETENTION_SYNCHRONISE_MS = 24 * 60 * 60 * 1000;

function maintenant(): number {
  return Date.now();
}

function nouvelIdentifiant(): string {
  return crypto.randomUUID();
}

/**
 * L'empreinte d'un opérateur.
 *
 * Ni identifiant Odoo, ni identifiant de connexion en clair : il suffit de
 * savoir si l'utilisateur courant est celui qui a saisi l'opération. Une
 * empreinte le dit, et ne dit rien d'autre à qui ouvrirait la base locale.
 */
export async function empreinteProprietaire(login: string): Promise<string> {
  const octets = new TextEncoder().encode(`dally-ops:owner:${login}`);
  const condensat = await crypto.subtle.digest('SHA-256', octets);
  return Array.from(new Uint8Array(condensat).slice(0, 16))
    .map((o) => o.toString(16).padStart(2, '0'))
    .join('');
}

export interface EntreeFile {
  readonly operation_type: TypeOperation;
  readonly owner_key: string;
  readonly payload: Record<string, unknown>;
  readonly resume: string;
  readonly target_reference?: string | null;
  readonly parent_local_id?: string | null;
  /**
   * Un identifiant déjà tiré, quand l'opération a d'abord été tentée en ligne.
   *
   * Le formulaire tire son identifiant avant le premier envoi ; si le réseau
   * coupe, l'opération entre en file **avec le même**. En tirer un neuf ici
   * transformerait une reprise en seconde opération métier — précisément ce
   * que toute cette mécanique existe pour empêcher.
   */
  readonly request_uuid?: string;
}

/**
 * Met une opération en file, confirmée par l'opérateur.
 *
 * C'est ici, et nulle part ailleurs, que naît le `request_uuid` : avant tout
 * réseau, une seule fois, pour toute la vie de l'opération.
 */
export async function mettreEnFile(entree: EntreeFile): Promise<MutationLocale> {
  const instant = maintenant();
  const mutation: MutationLocale = {
    local_id: nouvelIdentifiant(),
    request_uuid: entree.request_uuid ?? nouvelIdentifiant(),
    operation_type: entree.operation_type,
    owner_key: entree.owner_key,
    target_reference: entree.target_reference ?? null,
    parent_local_id: entree.parent_local_id ?? null,
    payload: entree.payload,
    resume: entree.resume,
    status: 'pending',
    created_at: instant,
    updated_at: instant,
    attempt_count: 0,
    next_retry_at: instant,
    last_attempt_at: null,
    last_error_code: null,
    last_error_message: null,
    server_reference: null,
  };
  await transaction(MAGASIN_MUTATIONS, 'readwrite', (t) =>
    requete(t.objectStore(MAGASIN_MUTATIONS).add(mutation)));
  return mutation;
}

export async function lireMutation(localId: string): Promise<MutationLocale | undefined> {
  return transaction(MAGASIN_MUTATIONS, 'readonly', (t) =>
    requete<MutationLocale | undefined>(
      t.objectStore(MAGASIN_MUTATIONS).get(localId)));
}

export async function toutesLesMutations(): Promise<MutationLocale[]> {
  const lignes = await transaction(MAGASIN_MUTATIONS, 'readonly', (t) =>
    requete<MutationLocale[]>(t.objectStore(MAGASIN_MUTATIONS).getAll()));
  return lignes.sort((a, b) => a.created_at - b.created_at);
}

/** Les opérations d'un opérateur, les plus anciennes d'abord. */
export async function mutationsDe(ownerKey: string): Promise<MutationLocale[]> {
  return (await toutesLesMutations()).filter((m) => m.owner_key === ownerKey);
}

async function ecrire(mutation: MutationLocale): Promise<MutationLocale> {
  await transaction(MAGASIN_MUTATIONS, 'readwrite', (t) =>
    requete(t.objectStore(MAGASIN_MUTATIONS).put(mutation)));
  return mutation;
}

/**
 * Applique un changement en relisant d'abord la valeur en base.
 *
 * Deux onglets peuvent viser la même opération ; travailler sur une copie en
 * mémoire écraserait silencieusement le travail de l'autre.
 */
async function modifier(
  localId: string,
  changement: (courante: MutationLocale) => MutationLocale,
): Promise<MutationLocale | undefined> {
  return transaction(MAGASIN_MUTATIONS, 'readwrite', async (t) => {
    const magasin = t.objectStore(MAGASIN_MUTATIONS);
    const courante = await requete<MutationLocale | undefined>(magasin.get(localId));
    if (!courante) return undefined;
    const suivante = changement(courante);
    await requete(magasin.put(suivante));
    return suivante;
  });
}

/** Marque une tentative comme réellement commencée. */
export function marquerEnCours(localId: string): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    status: 'syncing',
    attempt_count: courante.attempt_count + 1,
    last_attempt_at: maintenant(),
    updated_at: maintenant(),
  }));
}

/**
 * Enregistre le succès — et rien d'autre ne peut produire cet état.
 *
 * `serverReference` est ce que le serveur a réellement rendu : le vrai `Axxx`
 * pour une réception. C'est lui qui remplace l'identité locale à l'écran.
 */
export function marquerSynchronise(
  localId: string,
  serverReference: string | null,
): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    status: 'synced',
    server_reference: serverReference,
    last_error_code: null,
    last_error_message: null,
    updated_at: maintenant(),
  }));
}

/**
 * Repose l'opération pour une nouvelle tentative.
 *
 * Le `request_uuid` n'est pas touché : c'est tout l'objet de la manœuvre. Un
 * délai croissant évite de marteler un serveur qui a déjà des ennuis.
 */
export function reporter(
  localId: string,
  code: string,
  message: string,
): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => {
    const palier = PALIERS_RETENTE[
      Math.min(courante.attempt_count, PALIERS_RETENTE.length - 1)
    ] ?? 0;
    return {
      ...courante,
      status: 'pending',
      next_retry_at: maintenant() + palier,
      last_error_code: code,
      last_error_message: message,
      updated_at: maintenant(),
    };
  });
}

/** Un refus métier : l'opération ne partira pas telle quelle. */
export function marquerErreur(
  localId: string,
  code: string,
  message: string,
): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    status: 'error',
    last_error_code: code,
    last_error_message: message,
    updated_at: maintenant(),
  }));
}

/** La session a expiré : on suspend sans rien jeter. */
export function marquerAuthRequise(localId: string): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    status: 'auth_required',
    updated_at: maintenant(),
  }));
}

/** Un enfant dont le parent a définitivement échoué. */
export function marquerBloque(
  localId: string,
  message: string,
): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    status: 'blocked',
    last_error_code: 'parent_failed',
    last_error_message: message,
    updated_at: maintenant(),
  }));
}

/** Renseigne la cible d'un enfant une fois le parent synchronisé. */
export function resoudreCible(
  localId: string,
  reference: string,
): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    target_reference: reference,
    status: courante.status === 'blocked' ? 'pending' : courante.status,
    updated_at: maintenant(),
  }));
}

/** Remet une opération en erreur dans la file, à la demande de l'opérateur. */
export function reessayer(localId: string): Promise<MutationLocale | undefined> {
  return modifier(localId, (courante) => ({
    ...courante,
    status: 'pending',
    next_retry_at: maintenant(),
    // Le compteur repart : l'opérateur a probablement corrigé la cause, et
    // lui infliger quinze minutes d'attente serait absurde.
    attempt_count: 0,
    updated_at: maintenant(),
  }));
}

/** Réveille les opérations suspendues faute de session. */
export async function reprendreApresAuthentification(ownerKey: string): Promise<number> {
  const suspendues = (await mutationsDe(ownerKey))
    .filter((m) => m.status === 'auth_required');
  for (const mutation of suspendues) {
    await ecrire({
      ...mutation, status: 'pending', next_retry_at: maintenant(),
      updated_at: maintenant(),
    });
  }
  return suspendues.length;
}

/**
 * La prochaine opération réellement envoyable.
 *
 * Un enfant dont le parent n'est pas synchronisé n'est jamais rendu : l'envoyer
 * signifierait le poster sur un objet qui n'existe pas encore, ou pire, sur un
 * objet inventé.
 */
export async function prochaineAEnvoyer(
  ownerKey: string,
  instant = maintenant(),
  /** Ce qu'une passe en cours a déjà tenté : on n'y revient pas. */
  exclure: ReadonlySet<string> = new Set(),
): Promise<MutationLocale | null> {
  const toutes = await toutesLesMutations();
  const parIdentifiant = new Map(toutes.map((m) => [m.local_id, m]));
  for (const mutation of toutes) {
    if (mutation.owner_key !== ownerKey) continue;
    if (exclure.has(mutation.local_id)) continue;
    if (mutation.status !== 'pending') continue;
    if (mutation.next_retry_at > instant) continue;
    if (mutation.parent_local_id) {
      const parent = parIdentifiant.get(mutation.parent_local_id);
      if (!parent || parent.status !== 'synced') continue;
    }
    return mutation;
  }
  return null;
}

/** Les enfants directs d'une opération. */
export async function enfantsDe(localId: string): Promise<MutationLocale[]> {
  return (await toutesLesMutations())
    .filter((m) => m.parent_local_id === localId);
}

/**
 * Efface ce qui n'a plus lieu d'être conservé.
 *
 * Seules les opérations **synchronisées** et assez anciennes partent. Une
 * opération en attente survit à tout — y compris à une déconnexion : la perdre
 * reviendrait à perdre de la caisse déjà sortie.
 */
export async function purger(
  instant = maintenant(),
  retention = RETENTION_SYNCHRONISE_MS,
): Promise<number> {
  const toutes = await toutesLesMutations();
  const enfantsVivants = new Set(
    toutes.filter((m) => m.status !== 'synced')
      .map((m) => m.parent_local_id)
      .filter((valeur): valeur is string => Boolean(valeur)),
  );
  const aEffacer = toutes.filter((m) =>
    m.status === 'synced'
    && instant - m.updated_at > retention
    // Un parent dont un enfant attend encore reste : c'est lui qui porte la
    // référence sur laquelle l'enfant sera posté.
    && !enfantsVivants.has(m.local_id));
  if (aEffacer.length === 0) return 0;
  await transaction(MAGASIN_MUTATIONS, 'readwrite', async (t) => {
    const magasin = t.objectStore(MAGASIN_MUTATIONS);
    for (const mutation of aEffacer) await requete(magasin.delete(mutation.local_id));
  });
  return aEffacer.length;
}

// ─── Brouillons ─────────────────────────────────────────────────────

export async function enregistrerBrouillon(
  brouillon: Omit<BrouillonLocal, 'created_at' | 'updated_at'> & {
    created_at?: number;
  },
): Promise<BrouillonLocal> {
  const instant = maintenant();
  const ligne: BrouillonLocal = {
    ...brouillon,
    created_at: brouillon.created_at ?? instant,
    updated_at: instant,
  };
  await transaction(MAGASIN_BROUILLONS, 'readwrite', (t) =>
    requete(t.objectStore(MAGASIN_BROUILLONS).put(ligne)));
  return ligne;
}

export async function brouillonsDe(ownerKey: string): Promise<BrouillonLocal[]> {
  const lignes = await transaction(MAGASIN_BROUILLONS, 'readonly', (t) =>
    requete<BrouillonLocal[]>(t.objectStore(MAGASIN_BROUILLONS).getAll()));
  return lignes.filter((b) => b.owner_key === ownerKey)
    .sort((a, b) => a.created_at - b.created_at);
}

export async function supprimerBrouillon(localId: string): Promise<void> {
  await transaction(MAGASIN_BROUILLONS, 'readwrite', (t) =>
    requete(t.objectStore(MAGASIN_BROUILLONS).delete(localId)));
}

/**
 * Confirme un brouillon : il quitte l'appareil pour la file.
 *
 * C'est le passage `draft_local` → `pending`, et le moment où le
 * `request_uuid` est tiré.
 */
export async function confirmerBrouillon(
  localId: string,
  complement: Partial<EntreeFile> = {},
): Promise<MutationLocale | null> {
  const brouillons = await transaction(MAGASIN_BROUILLONS, 'readonly', (t) =>
    requete<BrouillonLocal[]>(t.objectStore(MAGASIN_BROUILLONS).getAll()));
  const brouillon = brouillons.find((b) => b.local_id === localId);
  if (!brouillon) return null;
  const mutation = await mettreEnFile({
    operation_type: brouillon.operation_type,
    owner_key: brouillon.owner_key,
    payload: brouillon.payload,
    resume: brouillon.resume,
    ...complement,
  });
  await supprimerBrouillon(localId);
  return mutation;
}

/** Un état d'ensemble, pour l'indicateur d'accueil. */
export interface EtatFile {
  readonly en_attente: number;
  readonly en_erreur: number;
  readonly etrangeres: number;
  readonly par_etat: Readonly<Partial<Record<EtatMutation, number>>>;
}

export async function etatDeLaFile(ownerKey: string): Promise<EtatFile> {
  const toutes = await toutesLesMutations();
  const par_etat: Partial<Record<EtatMutation, number>> = {};
  let en_attente = 0;
  let en_erreur = 0;
  let etrangeres = 0;
  for (const mutation of toutes) {
    if (mutation.owner_key !== ownerKey) {
      if (mutation.status !== 'synced') etrangeres += 1;
      continue;
    }
    par_etat[mutation.status] = (par_etat[mutation.status] ?? 0) + 1;
    if (mutation.status === 'pending' || mutation.status === 'syncing') en_attente += 1;
    if (mutation.status === 'error' || mutation.status === 'blocked'
        || mutation.status === 'auth_required') en_erreur += 1;
  }
  return { en_attente, en_erreur, etrangeres, par_etat };
}
