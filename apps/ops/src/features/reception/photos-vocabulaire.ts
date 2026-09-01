/**
 * Ce que l'écran dit des preuves photographiques, et ce qu'il en déduit.
 *
 * Séparé du composant pour la même raison qu'à l'étape précédente : ces règles
 * se vérifient sans monter un arbre React, et un texte lu par un opérateur
 * mérite d'être épinglé par un test plutôt que relu à l'œil.
 *
 * Séparé de `@/lib/ops/photos` parce qu'un fichier `'use client'` ne prend, de
 * `@/lib`, que des types : en importer une constante embarquerait la
 * configuration serveur dans la page.
 */

/** Les cinq natures, dans l'ordre où l'écran les propose. */
export const NATURES = [
  'reception', 'package', 'damage', 'preparation', 'other',
] as const;

export type Nature = (typeof NATURES)[number];

export const LIBELLES_NATURE: Readonly<Record<Nature, string>> = {
  reception: 'État à la réception',
  package: 'Emballage',
  damage: 'Dommage ou anomalie',
  preparation: 'Préparation avant expédition',
  other: 'Autre',
};

/**
 * La nature proposée d'emblée, selon l'état du dossier.
 *
 * Une proposition, jamais une contrainte. Le geste le plus probable est
 * présélectionné pour qu'un opérateur pressé n'ait rien à choisir ; il reste
 * libre d'en changer, et c'est le serveur qui valide.
 */
export function naturePardefaut(etat: string): Nature {
  if (etat === 'goods_received') return 'reception';
  if (etat === 'preparing' || etat === 'ready') return 'preparation';
  return 'other';
}

export function libelleNature(nature: string): string {
  return LIBELLES_NATURE[nature as Nature] ?? 'Autre';
}

export interface SuiviDeGeste {
  /** Clôt le geste courant : la prochaine demande tirera un identifiant neuf. */
  readonly terminer: () => void;
  /** L'identifiant du geste en cours, tiré à la première demande. */
  readonly identifiant: () => string;
  /** Ce qui est en cours, ou `null`. Pour l'introspection et les tests. */
  readonly enCours: () => string | null;
}

/**
 * Le suivi d'un geste d'envoi.
 *
 * ## Pourquoi l'identité n'est pas déduite du fichier
 *
 * Comparer nom, taille et nature paraissait suffisant : deux envois
 * consécutifs du même fichier sont bien le même geste. Mais deux fichiers
 * **différents** peuvent porter le même nom et la même taille — deux clichés
 * pris à la suite par le même appareil en font partie — et le geste précédent
 * serait alors réutilisé. Le serveur reconnaîtrait un rejeu, refuserait le
 * conflit d'intention, et l'opérateur croirait avoir envoyé sa seconde photo.
 *
 * L'identité ne se devine donc pas : elle se clôt explicitement. Une nouvelle
 * sélection, un changement de nature, une annulation ou une réussite
 * terminent le geste ; tout le reste — y compris une reprise réseau — le
 * poursuit.
 */
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

/** L'adresse par laquelle l'écran lit une photo. Jamais une URL de stockage. */
export function cheminPhoto(reference: string, photoUuid: string): string {
  return `/api/intakes/${encodeURIComponent(reference)}/photos/`
    + encodeURIComponent(photoUuid);
}

export type IssueEnvoi =
  | { readonly issue: 'ok' }
  | { readonly issue: 'refus'; readonly message: string }
  | { readonly issue: 'reessayable'; readonly message: string };

/**
 * Ce que l'opérateur lit après un envoi.
 *
 * Le message vient du serveur quand il en donne un : lui seul sait pourquoi il
 * a refusé. L'écran ne le réécrit pas, il ne fait que garantir qu'il y en a
 * toujours un.
 */
export function interpreterEnvoi(
  ok: boolean,
  corps: { success?: boolean; error?: string } | null,
): IssueEnvoi {
  if (ok && corps?.success === true) return { issue: 'ok' };
  return {
    issue: 'refus',
    message: typeof corps?.error === 'string' && corps.error
      ? corps.error
      : 'La photo n’a pas pu être enregistrée.',
  };
}

/** Le type précis se conserve : l'appelant lit `message` sans le redéduire. */
export type IssueReessayablePhoto = Extract<IssueEnvoi, { issue: 'reessayable' }>;

export function issueReseauPhoto(): IssueReessayablePhoto {
  return {
    issue: 'reessayable',
    message: 'Connexion interrompue. Vous pouvez réessayer le même envoi.',
  };
}

export function issueHorsLignePhoto(): IssueReessayablePhoto {
  return {
    issue: 'reessayable',
    message: 'Connexion requise pour envoyer une photo.',
  };
}

/** La date d'une preuve, lisible sans le fuseau du serveur. */
export function dateLisible(iso: string): string {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return '';
  const deux = (valeur: number) => String(valeur).padStart(2, '0');
  return `${deux(instant.getDate())}/${deux(instant.getMonth() + 1)}/`
    + `${instant.getFullYear()} ${deux(instant.getHours())}:`
    + `${deux(instant.getMinutes())}`;
}
