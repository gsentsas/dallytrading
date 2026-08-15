/**
 * Réponses communes aux routes portail.
 *
 * Toutes portent `Cache-Control: no-store`. Une réponse portail est propre à un
 * client : mise en cache quelque part sur le chemin — proxy, CDN, cache du
 * navigateur d'un poste partagé — elle finirait par être servie à un autre.
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
