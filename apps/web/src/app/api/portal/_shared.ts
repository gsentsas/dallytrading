/**
 * Réponses communes aux routes portail.
 *
 * Une réponse portail est propre à un client : mise en cache quelque part sur le
 * chemin — proxy, CDN, cache du navigateur d'un poste partagé — elle finirait par
 * être servie à quelqu'un d'autre.
 *
 * ## Ce que Next émet réellement
 *
 * Mesuré sur l'instance de test : Next **remplace** le `Cache-Control` des Route
 * Handlers dynamiques par `no-store` seul, et la directive `private` posée ici
 * n'apparaît pas dans la réponse. Ce n'est pas une perte — `no-store` interdit à
 * TOUT cache de stocker la réponse, partagé comme privé, ce qui est strictement
 * plus fort que `private`. On la conserve néanmoins : si Next cessait un jour de
 * réécrire l'en-tête, l'intention resterait exprimée.
 *
 * `Pragma: no-cache` survit, lui, et couvre les intermédiaires HTTP/1.0.
 */

import { NextResponse } from 'next/server';

const NO_STORE = {
  'Cache-Control': 'no-store, private, max-age=0',
  Pragma: 'no-cache',
} as const;

export function portalJson<T>(
  data: T,
  status = 200,
  headers: Record<string, string> = {},
): NextResponse {
  return NextResponse.json(
    { success: true, data },
    { status, headers: { ...NO_STORE, ...headers } },
  );
}

export function portalError(
  status: number,
  code: string,
  message: string,
  correlationId: string,
  headers: Record<string, string> = {},
): NextResponse {
  return NextResponse.json(
    { success: false, error: { code, message }, requestId: correlationId },
    { status, headers: { ...NO_STORE, ...headers } },
  );
}
