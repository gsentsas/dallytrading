/**
 * Le contrôle d'origine des requêtes qui écrivent ou qui cherchent.
 *
 * Le cookie Ops est déjà `SameSite=Lax`, donc un formulaire d'un autre site ne
 * l'emporte pas. Ce contrôle ajoute une seconde barrière, indépendante du
 * navigateur : si un jour un client mal configuré ou une extension relâchait
 * la première, la requête resterait refusée côté serveur.
 *
 * Une requête sans en-tête `Origin` est acceptée : les clients non-navigateurs
 * légitimes n'en envoient pas, et `SameSite` couvre déjà le cas du navigateur.
 * Ce qui est refusé, c'est une origine **présente et différente** — le seul
 * signal réellement informatif.
 */

import { opsEnv } from '@/lib/env';

export function origineAcceptable(requete: Request): boolean {
  const origine = requete.headers.get('origin');
  if (!origine) return true;
  try {
    return new URL(origine).origin === new URL(opsEnv().OPS_PUBLIC_URL).origin;
  } catch {
    return false;
  }
}
