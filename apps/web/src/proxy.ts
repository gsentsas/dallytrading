/**
 * Redirection optimiste vers /connexion — confort, PAS sécurité.
 *
 * ## Ce que ce fichier fait exactement
 *
 * Il regarde si le cookie `dt_portal_session` est présent. C'est tout. Il ne
 * l'ouvre pas, ne vérifie ni sa signature ni son expiration, et n'interroge pas
 * Odoo. Un cookie forgé au hasard passe ce contrôle.
 *
 * ## Pourquoi c'est acceptable
 *
 * Parce que rien ne s'y appuie. Chaque page privée appelle `requirePortalSession()`,
 * qui interroge Odoo et laisse Odoo refuser. Le proxy évite seulement d'afficher
 * un squelette de page à un visiteur non connecté avant que le serveur ne le
 * redirige — un gain d'affichage, pas une barrière.
 *
 * Le proxy s'exécute dans un runtime restreint, sans accès à `node:crypto` complet
 * ni au réseau vers Odoo. Y placer la vraie vérification serait donc soit
 * impossible, soit une version dégradée de celle qui existe déjà plus bas. Et une
 * vérification dégradée en amont est pire que pas de vérification : elle invite à
 * relâcher celle d'en dessous.
 *
 * Next 16.3 nomme ce fichier `proxy.ts` (l'ancien `middleware.ts` reste accepté).
 */

import { NextResponse, type NextRequest } from 'next/server';

import { PORTAL_COOKIE } from '@/lib/portal/session';

export function proxy(request: NextRequest): NextResponse {
  const hasCookie = Boolean(request.cookies.get(PORTAL_COOKIE)?.value);
  if (hasCookie) {
    return NextResponse.next();
  }

  const target = new URL('/connexion', request.url);
  // Seul le chemin est transmis, jamais l'URL absolue : `safeNextPath` la
  // refuserait, et la reconstruire côté /connexion rouvrirait la porte que
  // cette contrainte ferme.
  target.searchParams.set('next', request.nextUrl.pathname);
  return NextResponse.redirect(target);
}

export const config = {
  matcher: ['/espace-client/:path*'],
};
