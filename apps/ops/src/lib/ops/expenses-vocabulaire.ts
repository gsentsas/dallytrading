/**
 * Le vocabulaire partagé des dépenses — et rien d'autre.
 *
 * ## Pourquoi ce fichier existe séparément
 *
 * `expenses.ts` parle à Odoo : il remonte, par sa chaîne d'imports, jusqu'à
 * `lib/env.ts`, qui est un module serveur et refuse de s'exécuter dans un
 * navigateur. Un composant client qui y prendrait ne serait-ce qu'une
 * constante embarquerait toute cette chaîne et casserait la page.
 *
 * C'est arrivé, et le parcours de bout en bout l'a montré avant la mise en
 * ligne. D'où ce module : quelques valeurs, aucun import, sûr des deux côtés.
 * Les types, eux, se prennent directement dans `expenses.ts` — un
 * `import type` disparaît à la compilation et n'emporte rien avec lui.
 */

/**
 * Les modes de paiement d'une dépense.
 *
 * Volontairement distincts des canaux d'encaissement client : ceux-là portent
 * un journal comptable et produisent une écriture. Une dépense de terrain n'en
 * produit pas — elle dit seulement comment l'argent est sorti.
 */
export const MODES_PAIEMENT = ['cash', 'wave', 'bank', 'other'] as const;

export type ModePaiement = (typeof MODES_PAIEMENT)[number];

export const LIBELLES_MODE: Readonly<Record<ModePaiement, string>> = {
  cash: 'Espèces',
  wave: 'Wave',
  bank: 'Virement',
  other: 'Autre',
};

/**
 * Le poids maximal d'un justificatif : dix mébioctets.
 *
 * Répété ici et dans Odoo, à dessein. Le serveur est l'autorité — c'est lui
 * qui refuse ce qui dépasse. Cette copie ne sert qu'à éviter d'envoyer une
 * photo qu'on sait déjà trop lourde, ce qui, sur une 4G d'entrepôt, économise
 * une minute et une déception.
 */
export const TAILLE_MAXIMALE_JUSTIFICATIF = 10 * 1024 * 1024;
