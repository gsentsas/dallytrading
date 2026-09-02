import { NextResponse, type NextRequest } from 'next/server';

/**
 * Le seul refus qui doit précéder le routage.
 *
 * Une URI dont l'encodage pour-cent est invalide — `A%ZZ` — fait échouer le
 * décodage des segments dynamiques d'App Router **avant** que le gestionnaire
 * de route ne soit appelé. Mesuré : la réponse était un 500, aussi bien sur
 * `/api/intakes/<ref>/legacy-detail` que sur la page. Aucune validation
 * écrite dans la route ne pouvait l'intercepter, puisque la route n'était
 * jamais atteinte.
 *
 * Ce filtre n'a donc pas de doublon ailleurs : il traite le seul cas que la
 * route ne peut pas voir. La forme de la référence, elle, reste jugée par
 * `normaliserReference` — ici on ne vérifie que la lisibilité de l'URI.
 *
 * Le `matcher` le borne aux deux chemins de la fiche en lecture seule : un
 * middleware large deviendrait un second endroit où raisonner sur les
 * chemins, et divergerait.
 */
export function middleware(requete: NextRequest) {
  try {
    decodeURIComponent(requete.nextUrl.pathname);
  } catch {
    const versApi = requete.nextUrl.pathname.startsWith('/api/');
    if (versApi) {
      return NextResponse.json(
        { success: false, error: 'Référence de dossier invalide.' },
        { status: 400, headers: { 'Cache-Control': 'private, no-store, max-age=0' } },
      );
    }
    return new NextResponse('Référence de dossier invalide.', {
      status: 400,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Cache-Control': 'private, no-store, max-age=0',
      },
    });
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    '/api/intakes/:reference/legacy-detail',
    '/reception/dossier/:reference/lecture-seule',
  ],
};
