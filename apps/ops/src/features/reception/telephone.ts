/**
 * La règle des neuf chiffres, côté navigateur.
 *
 * Elle existe déjà côté serveur, où elle fait autorité. La répéter ici ne la
 * duplique pas pour rien : elle évite d'envoyer « 77 » sur le réseau, et elle
 * permet de le dire à l'opérateur tout de suite plutôt qu'après un aller-retour
 * dans un entrepôt où la couverture est mauvaise.
 *
 * Neuf, parce qu'un abonné sénégalais a neuf chiffres : comparer la fin du
 * numéro absorbe toutes les façons de l'écrire — +221, 00221, 221, ou rien.
 */

export const CHIFFRES_MINIMUM = 9;

export function chiffres(valeur: string): string {
  return valeur.replace(/\D/g, '');
}

export function telephoneUtilisable(valeur: string): boolean {
  return chiffres(valeur).length >= CHIFFRES_MINIMUM;
}

/**
 * Une adresse utilisable, au sens le plus modeste du terme.
 *
 * On ne cherche pas à valider une adresse électronique — personne n'y arrive
 * par expression régulière. On vérifie seulement qu'il y a quelque chose de
 * part et d'autre d'un `@`, pour ne pas envoyer « client » au serveur.
 */
export function emailUtilisable(valeur: string): boolean {
  const parties = valeur.trim().split('@');
  if (parties.length !== 2) return false;
  const [avant, apres] = parties as [string, string];
  return avant.length > 0 && apres.includes('.') && !apres.startsWith('.');
}
