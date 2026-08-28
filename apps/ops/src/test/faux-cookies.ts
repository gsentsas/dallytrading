/**
 * Un magasin de cookies de banc, à la place de `next/headers`.
 *
 * Il retient aussi les options passées à `set`, parce que la sécurité du
 * cookie tient autant à ses attributs qu'à son contenu.
 */

import { vi } from 'vitest';

export interface EcritureCookie {
  readonly nom: string;
  readonly valeur: string;
  readonly options: Record<string, unknown>;
}

export const magasinCookies = new Map<string, string>();
export const ecrituresCookies: EcritureCookie[] = [];

export function reinitialiserCookies(): void {
  magasinCookies.clear();
  ecrituresCookies.length = 0;
}

/**
 * Le remplacement de `next/headers`.
 *
 * Déclaré au niveau du module : Vitest remonte les appels `vi.mock` en tête de
 * fichier, et l'écrire dans une fonction laisserait croire à un ordre
 * d'exécution qui n'est pas le vrai.
 */
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (nom: string) =>
      magasinCookies.has(nom) ? { name: nom, value: magasinCookies.get(nom) } : undefined,
    set: (nom: string, valeur: string, options: Record<string, unknown> = {}) => {
      ecrituresCookies.push({ nom, valeur, options });
      if (options.maxAge === 0 || valeur === '') magasinCookies.delete(nom);
      else magasinCookies.set(nom, valeur);
    },
  }),
}));
