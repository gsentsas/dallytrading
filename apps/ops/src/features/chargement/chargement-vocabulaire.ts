/**
 * Les décisions de l'écran de chargement, sorties du composant.
 *
 * Séparer ces fonctions du rendu n'est pas une élégance : c'est ce qui permet
 * de les éprouver une par une, sans navigateur, y compris les cas qu'un
 * parcours ne produit qu'une fois par an — une lecture qui échoue, un geste
 * rejoué, un colis bloqué ailleurs.
 */

import type {
  ActionChargement, ColisChargement, DetailChargement, ResumeChargement,
} from '@/lib/ops/loading';

/** Ce que l'opérateur lit à la place d'un code. */
export const LIBELLE_STATUT: Readonly<Record<string, string>> = {
  not_loaded: 'À charger',
  partial: 'Partiel',
  loaded: 'Chargé',
  blocked: 'Bloqué',
};

export function libelleStatut(statut: string): string {
  return LIBELLE_STATUT[statut] ?? statut;
}

/**
 * Le compte, jamais un pourcentage.
 *
 * « 12 sur 18 » se vérifie d'un coup d'œil sur la pile. « 83 % » ne se
 * vérifie pas du tout, et se trompe dès que les colis n'ont pas le même
 * poids. Le serveur ne calcule aucun taux ; l'écran n'en invente pas.
 */
export function resumeLisible(resume: ResumeChargement): string {
  return `${resume.packages_loaded} sur ${resume.packages_expected} colis`;
}

export function resteALire(resume: ResumeChargement): string {
  const morceaux: string[] = [];
  if (resume.packages_remaining) {
    morceaux.push(`${resume.packages_remaining} à charger`);
  }
  if (resume.packages_partial) {
    morceaux.push(`${resume.packages_partial} partiel${resume.packages_partial > 1 ? 's' : ''}`);
  }
  if (resume.packages_blocked) {
    morceaux.push(`${resume.packages_blocked} bloqué${resume.packages_blocked > 1 ? 's' : ''}`);
  }
  return morceaux.join(' · ');
}

/** Un départ est complet quand plus rien ne manque et que rien ne bloque. */
export function departComplet(resume: ResumeChargement): boolean {
  return resume.packages_expected > 0
    && resume.packages_loaded === resume.packages_expected;
}

/**
 * Le geste proposé pour ce colis, ou aucun.
 *
 * `can_load` et `can_unload` viennent du serveur. L'écran ne les recalcule
 * pas : il choisit seulement lequel des deux montrer, et n'en montre aucun
 * quand la collecte est close ou le colis bloqué ailleurs.
 */
export function gesteProposé(colis: ColisChargement): ActionChargement | null {
  if (colis.can_load) return 'load';
  if (colis.can_unload) return 'unload';
  return null;
}

export function libelleGeste(action: ActionChargement): string {
  return action === 'load' ? 'CHARGER' : 'RETIRER';
}

export interface EtatAffichage {
  readonly chargement: boolean;
  readonly lectureEchouee: boolean;
  readonly detail: DetailChargement | null;
}

export interface Affichage {
  readonly indisponible: boolean;
  readonly aucunDossier: boolean;
  readonly liste: boolean;
  readonly ferme: boolean;
}

/**
 * Ce que l'écran montre. Une lecture qui échoue n'est pas un départ vide.
 *
 * Les confondre ferait croire à l'opérateur qu'il n'a rien à charger — et il
 * laisserait la pile au sol.
 */
export function determinerAffichage(etat: EtatAffichage): Affichage {
  if (etat.chargement) {
    return { indisponible: false, aucunDossier: false, liste: false, ferme: false };
  }
  if (etat.lectureEchouee || etat.detail === null) {
    return { indisponible: true, aucunDossier: false, liste: false, ferme: false };
  }
  return {
    indisponible: false,
    aucunDossier: etat.detail.shipments.length === 0,
    liste: etat.detail.shipments.length > 0,
    ferme: !etat.detail.can_load,
  };
}

export type Lecture =
  | { readonly issue: 'ok'; readonly donnees: DetailChargement }
  | { readonly issue: 'echec' };

/** Une lecture ne rend « ok » que sur un vrai succès annoncé par le serveur. */
export async function lireChargement(
  appeler: () => Promise<{ ok: boolean; corps: unknown }>,
): Promise<Lecture> {
  try {
    const { ok, corps } = await appeler();
    if (!ok || corps === null || typeof corps !== 'object') return { issue: 'echec' };
    const enveloppe = corps as { success?: unknown; data?: unknown };
    if (enveloppe.success !== true) return { issue: 'echec' };
    const data = enveloppe.data as { loading?: unknown } | null;
    if (!data || typeof data !== 'object' || !data.loading) return { issue: 'echec' };
    return { issue: 'ok', donnees: data.loading as DetailChargement };
  } catch {
    return { issue: 'echec' };
  }
}

export type Envoi =
  | { readonly issue: 'ok'; readonly donnees: DetailChargement }
  | { readonly issue: 'refus'; readonly message: string };

const REFUS_PAR_DEFAUT = 'Le geste n’a pas pu être enregistré.';

/**
 * Le message vient du serveur, qui seul sait pourquoi il refuse.
 *
 * En inventer un ici ferait dire à l'écran « collecte close » alors que le
 * serveur a peut-être refusé pour une autre raison.
 */
export function interpreterEnvoi(ok: boolean, corps: unknown): Envoi {
  if (corps === null || typeof corps !== 'object') {
    return { issue: 'refus', message: REFUS_PAR_DEFAUT };
  }
  const enveloppe = corps as { success?: unknown; error?: unknown; data?: unknown };
  if (ok && enveloppe.success === true) {
    const data = enveloppe.data as { loading?: unknown } | null;
    if (data && typeof data === 'object' && data.loading) {
      return { issue: 'ok', donnees: data.loading as DetailChargement };
    }
    return { issue: 'refus', message: REFUS_PAR_DEFAUT };
  }
  const message = typeof enveloppe.error === 'string' && enveloppe.error
    ? enveloppe.error : REFUS_PAR_DEFAUT;
  return { issue: 'refus', message };
}

/**
 * Un identifiant de geste par colis **et** par action.
 *
 * Un seul identifiant courant, comme pour les événements, ne convient pas
 * ici : l'opérateur enchaîne un geste par colis, et deux colis ne sont pas la
 * même intention. L'identifiant est tiré une fois par couple, conservé tant
 * que le geste n'a pas abouti — une reprise réseau rejoue donc exactement le
 * même geste — puis clos par le succès.
 */
export interface SuiviDeGestes {
  identifiant(colis: string, action: ActionChargement): string;
  terminer(colis: string, action: ActionChargement): void;
}

export function creerSuiviDeGestes(tirer: () => string): SuiviDeGestes {
  const encours = new Map<string, string>();
  const cle = (colis: string, action: ActionChargement) => `${colis}:${action}`;
  return {
    identifiant(colis, action) {
      const index = cle(colis, action);
      const existant = encours.get(index);
      if (existant !== undefined) return existant;
      const neuf = tirer();
      encours.set(index, neuf);
      return neuf;
    },
    terminer(colis, action) {
      encours.delete(cle(colis, action));
    },
  };
}
