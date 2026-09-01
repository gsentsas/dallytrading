/**
 * Ce que l'écran dit des événements, et ce qu'il en déduit.
 *
 * Séparé du composant pour la même raison qu'aux étapes précédentes : ces
 * règles se vérifient sans monter un arbre React. Séparé de `@/lib/ops/events`
 * parce qu'un fichier `'use client'` ne prend, de `@/lib`, que des types.
 *
 * ## Ce que ce module ne contient pas
 *
 * La liste des natures. Elle vient du serveur avec sa règle de note : le jour
 * où une huitième apparaît, elle descend sans qu'aucune ligne d'ici ne change.
 * Recopier la liste ferait un second vocabulaire, qui divergerait.
 */

/** La borne du serveur, redite pour refuser avant le réseau. */
export const LONGUEUR_NOTE = 1000;

/** Le minimum qui distingue une note d'un caractère resté sous le doigt. */
export const LONGUEUR_NOTE_MINIMALE = 3;

export interface NatureProposable {
  readonly kind: string;
  readonly label: string;
  readonly note_required: boolean;
}

/**
 * La demande est-elle envoyable ?
 *
 * Reproduit exactement la règle du serveur, et pour une seule raison : que le
 * bouton soit gris avant que l'opérateur n'appuie, plutôt qu'un refus après
 * l'aller-retour. Le serveur reste l'autorité — il revalide tout.
 */
export function demandeValide(
  nature: NatureProposable | undefined, note: string,
): boolean {
  if (!nature) return false;
  const propre = note.trim();
  if (propre.length > LONGUEUR_NOTE) return false;
  if (nature.note_required) return propre.length >= LONGUEUR_NOTE_MINIMALE;
  return true;
}

/** Ce qui manque, dit à l'opérateur plutôt que deviné par lui. */
export function motifDIndisponibilite(
  nature: NatureProposable | undefined, note: string,
): string {
  if (!nature) return 'Choisissez une nature d’événement.';
  const propre = note.trim();
  if (propre.length > LONGUEUR_NOTE) {
    return `La note dépasse ${LONGUEUR_NOTE} caractères.`;
  }
  if (nature.note_required && propre.length < LONGUEUR_NOTE_MINIMALE) {
    return 'Cette nature demande une note : décrivez ce que vous avez constaté.';
  }
  return '';
}

/**
 * Faut-il repartir d'un identifiant de geste neuf ?
 *
 * Même contrat qu'aux photos : la clôture est explicite. Une nature qui change
 * ou une note qui change, c'est une autre intention — et le serveur la
 * comparerait à celle du premier envoi, puis refuserait le conflit.
 */
export interface SuiviDeGeste {
  readonly terminer: () => void;
  readonly identifiant: () => string;
  readonly enCours: () => string | null;
}

export function creerSuiviDeGeste(nouvelIdentifiant: () => string): SuiviDeGeste {
  let courant: string | null = null;
  return {
    terminer() { courant = null; },
    identifiant() {
      courant ??= nouvelIdentifiant();
      return courant;
    },
    enCours() { return courant; },
  };
}

export type IssueEvenement =
  | { readonly issue: 'ok' }
  | { readonly issue: 'refus'; readonly message: string };

/**
 * Ce que l'opérateur lit après un envoi.
 *
 * Le message vient du serveur quand il en donne un : lui seul sait pourquoi il
 * a refusé. L'écran ne le réécrit pas, il garantit seulement qu'il y en a un.
 */
export function interpreterEnvoi(
  ok: boolean,
  corps: { success?: boolean; error?: string } | null,
): IssueEvenement {
  if (ok && corps?.success === true) return { issue: 'ok' };
  return {
    issue: 'refus',
    message: typeof corps?.error === 'string' && corps.error
      ? corps.error
      : 'L’événement n’a pas pu être consigné.',
  };
}

/** La date d'un événement, lisible sans le fuseau du serveur. */
export function dateLisible(iso: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return '';
  const deux = (valeur: number) => String(valeur).padStart(2, '0');
  return `${deux(instant.getDate())}/${deux(instant.getMonth() + 1)}/`
    + `${instant.getFullYear()} ${deux(instant.getHours())}:`
    + `${deux(instant.getMinutes())}`;
}

/** D'où vient l'événement, dit en mots plutôt qu'en code. */
export function libelleSource(source: string): string {
  return source === 'ops' ? 'Terrain' : 'Back-office';
}
