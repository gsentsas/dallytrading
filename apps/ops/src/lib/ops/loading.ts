/**
 * Le contrat du chargement d'un départ.
 *
 * ## Ce que le navigateur envoie
 *
 * Trois champs : l'identifiant du geste, l'action, et l'identité opaque du
 * colis. Jamais une quantité — le geste porte sur le colis entier — et jamais
 * un identifiant de base. `.strict()` fait tomber la demande si un champ de
 * plus s'y glisse, plutôt que de l'ignorer.
 *
 * ## Ce que le navigateur reçoit
 *
 * Des comptes, jamais un pourcentage : au quai, la question est *lesquels*
 * manquent. Aucune clé primaire, aucune société, aucun identifiant
 * d'utilisateur ; le colis se désigne par `reference`, opaque et stable.
 *
 * ## Ce qui n'existe pas ici
 *
 * Ni clôture de collecte, ni mise au départ, ni enregistrement de départ. Ces
 * gestes engagent le dossier maître et restent au back-office : le contrat ne
 * les nomme pas, pour qu'aucun écran ne puisse les appeler.
 */

import { z } from 'zod';

import { opsGet, opsPost } from '@/lib/auth/odoo-ops';

/** Ce qu'un colis vaut sur ce départ. Décidé par le serveur, jamais ici. */
export const statutColis = z.enum(['not_loaded', 'partial', 'loaded', 'blocked']);

export type StatutColis = z.infer<typeof statutColis>;

/** Les deux seuls gestes. */
export const actionChargement = z.enum(['load', 'unload']);

export type ActionChargement = z.infer<typeof actionChargement>;

/**
 * Les bornes des listes, mesurées plutôt que devinées.
 *
 * Un plafond trop bas ne dégrade pas l'affichage : il fait échouer l'analyse
 * de **toute** la réponse, et l'écran répond alors 503. Un premier jet plafonné
 * à 500 dossiers a été pris en défaut par une base de banc qui en comptait 689,
 * accumulés par cinq jours de parcours automatisés.
 *
 * Les chiffres retenus laissent donc une marge franche au-dessus du réel
 * observé en production le 2 septembre 2026 : le départ actif y porte
 * 34 dossiers, 118 colis au total, et 4 départs sont regardables. Ils restent
 * bornés — un contrat sans borne accepterait une réponse de taille
 * arbitraire — mais la borne ne doit jamais être atteinte par des données
 * légitimes.
 */
export const BORNE_DEPARTS = 200;
export const BORNE_DOSSIERS = 5000;
export const BORNE_COLIS = 500;

export const colisChargement = z.object({
  reference: z.string().min(1).max(64),
  description: z.string(),
  goods_category: z.string(),
  package_type: z.string().max(40),
  expected_quantity: z.number().int(),
  loaded_quantity: z.number().int(),
  remaining_quantity: z.number().int(),
  exact_weight_kg: z.number(),
  volume_cbm: z.number(),
  status: statutColis,
  can_load: z.boolean(),
  can_unload: z.boolean(),
  blocker: z.string().nullable(),
}).strict();

export const dossierChargement = z.object({
  // Sans borne minimale : un dossier repris peut n'avoir aucune référence
  // externe, et refuser ici la chaîne vide effacerait tout le départ.
  reference: z.string(),
  local_reference: z.string(),
  customer: z.object({ name: z.string() }).strict(),
  complete: z.boolean(),
  packages: z.array(colisChargement).max(BORNE_COLIS),
}).strict();

export const resumeChargement = z.object({
  shipments_expected: z.number().int(),
  shipments_complete: z.number().int(),
  packages_expected: z.number().int(),
  packages_loaded: z.number().int(),
  packages_partial: z.number().int(),
  packages_remaining: z.number().int(),
  packages_blocked: z.number().int(),
  quantity_expected: z.number().int(),
  quantity_loaded: z.number().int(),
  weight_expected_kg: z.number(),
  weight_loaded_kg: z.number(),
  volume_expected_cbm: z.number(),
  volume_loaded_cbm: z.number(),
}).strict();

/** Un lieu, tel que les écrans le lisent : la ville d'abord. */
export const lieu = z.object({
  country_code: z.string().max(8),
  city: z.string().max(120),
  location: z.string().max(120),
}).strict();

const entete = {
  reference: z.string().min(1).max(120),
  state: z.string().max(40),
  state_label: z.string().max(120),
  transport_mode: z.string().max(40),
  direction: z.string().max(40),
  origin: lieu,
  destination: lieu,
  collection_close_on: z.string().max(40),
  scheduled_departure: z.string().max(40),
  can_load: z.boolean(),
};

export const departChargement = z.object({
  ...entete,
  summary: resumeChargement,
}).strict();

export const detailChargement = z.object({
  ...entete,
  summary: resumeChargement,
  shipments: z.array(dossierChargement).max(BORNE_DOSSIERS),
}).strict();

export const listeChargement = z.object({
  consolidations: z.array(departChargement).max(BORNE_DEPARTS),
}).strict();

export const chargementApplique = z.object({
  replayed: z.boolean(),
  loading: detailChargement,
}).strict();

export type ColisChargement = z.infer<typeof colisChargement>;
export type DossierChargement = z.infer<typeof dossierChargement>;
export type ResumeChargement = z.infer<typeof resumeChargement>;
export type DepartChargement = z.infer<typeof departChargement>;
export type DetailChargement = z.infer<typeof detailChargement>;
export type ListeChargement = z.infer<typeof listeChargement>;
export type ChargementApplique = z.infer<typeof chargementApplique>;

/** Exactement ce qu'un geste envoie. Aucune quantité : le colis est entier. */
export const demandeChargement = z.object({
  request_uuid: z.string().uuid(),
  action: actionChargement,
  package_reference: z.string().min(1).max(64),
}).strict();

export type DemandeChargement = z.infer<typeof demandeChargement>;

/**
 * La forme d'une référence de départ.
 *
 * Le souligné est admis : la production n'en compte aucun sur les départs,
 * mais cinq dossiers en portent, et une passerelle qui refuse ce que la base
 * accepte finit toujours par rendre un dossier inatteignable.
 */
export const FORME_REFERENCE_DEPART = /^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$/;

export const LONGUEUR_REFERENCE_MAXIMALE = 120;

/**
 * Normalise la référence reçue de l'URL, ou refuse.
 *
 * Aucun rognage : une référence encadrée d'espaces n'est pas la même
 * référence, et la corriger en silence masquerait un lien fautif au lieu de
 * le signaler.
 */
export function normaliserReferenceDepart(brute: unknown): string | null {
  if (typeof brute !== 'string') return null;
  if (brute !== brute.trim()) return null;
  if (!brute || brute.length > LONGUEUR_REFERENCE_MAXIMALE) return null;
  return FORME_REFERENCE_DEPART.test(brute) ? brute : null;
}

function ressource(reference: string): string {
  const propre = normaliserReferenceDepart(reference);
  if (propre === null) throw new Error('Référence de départ invalide.');
  return `loading/consolidations/${propre}`;
}

export async function fetchLoadings(
  sessionId: string, correlationId: string,
): Promise<ListeChargement> {
  return listeChargement.parse(
    await opsGet('loading/consolidations', sessionId, correlationId));
}

export async function fetchLoading(
  reference: string, sessionId: string, correlationId: string,
): Promise<{ loading: DetailChargement }> {
  return z.object({ loading: detailChargement }).strict().parse(
    await opsGet(ressource(reference), sessionId, correlationId));
}

export async function applyLoading(
  reference: string,
  demande: DemandeChargement,
  sessionId: string,
  correlationId: string,
): Promise<ChargementApplique> {
  return chargementApplique.parse(
    await opsPost(ressource(reference), demande, sessionId, correlationId));
}
