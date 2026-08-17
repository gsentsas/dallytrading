/**
 * Le site est-il servi en HTTPS ?
 *
 * ## Pourquoi cette question plutôt que `ENVIRONMENT === 'production'`
 *
 * `ENVIRONMENT` **n'est pas défini** dans `apps/web/.env.production`, le fichier
 * que systemd charge réellement. Le schéma Zod le fait donc retomber sur
 * `development` en production, silencieusement.
 *
 * La conséquence a été mesurée pendant la préparation du déploiement : le cookie
 * de panier serait parti **sans l'attribut `Secure`**, donc en clair à la première
 * requête `http://`. Le portail avait déjà rencontré ce piège et l'avait résolu
 * ainsi — voir `wantsSecureCookie` dans `lib/portal/auth.ts`, dont le commentaire
 * décrit exactement la même erreur.
 *
 * Le schéma de l'URL du site est la condition sous laquelle un cookie `Secure`
 * fonctionne : requis en https, empêchant la connexion en http local. Il ne peut
 * pas se désynchroniser de la réalité, contrairement à une variable qu'on peut
 * oublier de renseigner.
 */

import { getServerEnv } from '@/lib/env';

export function siteIsHttps(): boolean {
  return getServerEnv().NEXT_PUBLIC_SITE_URL.startsWith('https://');
}
