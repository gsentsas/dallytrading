/**
 * Ce que l'écran dit quand la fiche ne se lit pas.
 *
 * Séparé du composant pour la même raison qu'ailleurs : ces messages se
 * vérifient sans monter un arbre React. Chaque issue appelle un geste
 * différent, et c'est pour cela qu'elles ne sont pas fondues en une seule.
 */

export type IssueLecture =
  | 'introuvable'
  | 'debit'
  | 'indisponible'
  | 'reseau'
  | 'session'
  | 'reference';

const MESSAGES: Record<IssueLecture, string> = {
  introuvable: 'Dossier introuvable.',
  reference: 'Cette référence de dossier n’est pas valide.',
  debit: 'Trop de consultations. Réessayez dans quelques minutes.',
  indisponible: 'Service momentanément indisponible.',
  reseau: 'Connexion interrompue. Réessayez.',
  session: 'Session expirée. Reconnectez-vous.',
};

export function messageDeLecture(issue: IssueLecture): string {
  return MESSAGES[issue];
}

/**
 * Ce que dit un statut HTTP du BFF.
 *
 * Quatre refus distincts, quatre gestes différents : une référence fausse se
 * corrige, un dossier absent se cherche ailleurs, un débit atteint s'attend,
 * une panne s'escalade. Tout ce qui n'est pas prévu tombe en « indisponible »
 * plutôt que d'inventer un diagnostic.
 */
export function issueDuStatut(statut: number): IssueLecture {
  if (statut === 400) return 'reference';
  if (statut === 401) return 'session';
  if (statut === 404) return 'introuvable';
  if (statut === 429) return 'debit';
  return 'indisponible';
}

import type { FicheLegacy } from '@/lib/ops/legacy-intake';

/**
 * L'état d'une lecture, **et le dossier auquel il appartient**.
 *
 * La référence est portée dans l'état, pas seulement dans la prop : sans
 * elle, une fiche déjà chargée survit au changement de dossier, et l'écran
 * montre les données d'un client sous l'adresse d'un autre. Le même piège que
 * `A001` ailleurs dans ce chantier, à un autre étage.
 */
export type EtatLecture =
  | { readonly reference: string; readonly phase: 'chargement' }
  | { readonly reference: string; readonly phase: 'fiche'; readonly fiche: FicheLegacy }
  | { readonly reference: string; readonly phase: 'issue'; readonly issue: IssueLecture };

export function chargementDe(reference: string): EtatLecture {
  return { reference, phase: 'chargement' };
}

/**
 * L'état qui s'applique vraiment au dossier demandé.
 *
 * Un état qui parle d'un autre dossier ne vaut rien ici : on repart d'un
 * chargement plutôt que de l'afficher. La fiche obsolète devient ainsi
 * impossible à rendre, au lieu d'être seulement improbable.
 */
export function etatApplicable(etat: EtatLecture, reference: string): EtatLecture {
  return etat.reference === reference ? etat : chargementDe(reference);
}

/**
 * Lit, puis ne pose l'état que si la lecture vaut encore.
 *
 * `obsolete()` est consulté **après** l'attente : une réponse lente pour le
 * dossier A ne doit jamais réécrire ce que le dossier B vient d'afficher.
 * Rien n'est posé dans ce cas — ni fiche, ni issue.
 */
export async function chargerFiche(
  reference: string,
  appeler: () => Promise<{ ok: boolean; statut: number; corps: unknown }>,
  poser: (etat: EtatLecture) => void,
  obsolete: () => boolean,
): Promise<void> {
  const resultat = await lireFicheLegacy(appeler);
  if (obsolete()) return;
  poser(resultat.issue === 'ok'
    ? { reference, phase: 'fiche', fiche: resultat.fiche as FicheLegacy }
    : { reference, phase: 'issue', issue: resultat.issue });
}

export type ResultatLecture =
  | { readonly issue: 'ok'; readonly fiche: unknown }
  | { readonly issue: IssueLecture };

/**
 * Ce que vaut une tentative de lecture, sans jamais lever.
 *
 * L'appel est reçu en paramètre pour que chaque issue se vérifie sans
 * navigateur — même parti qu'aux étapes précédentes. Et parce que cette
 * fonction ne lève pas, le composant peut poser son état en une seule fois
 * après l'attente, au lieu d'enchaîner des `setState` dans un `try`/`catch`
 * synchrone que React déconseille.
 */
export async function lireFicheLegacy(
  appeler: () => Promise<{ ok: boolean; statut: number; corps: unknown }>,
): Promise<ResultatLecture> {
  try {
    const { ok, statut, corps } = await appeler();
    const charge = corps as { success?: unknown; data?: unknown } | null;
    if (ok && charge?.success === true && charge.data) {
      return { issue: 'ok', fiche: charge.data };
    }
    // Un 200 sans charge exploitable n'est pas un succès : le traiter comme
    // tel afficherait une fiche vide plutôt qu'un incident.
    return { issue: ok ? 'indisponible' : issueDuStatut(statut) };
  } catch {
    return { issue: 'reseau' };
  }
}
