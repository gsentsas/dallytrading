/**
 * `POST /api/auth/logout` — fermeture de session.
 *
 * Idempotent : sans cookie, avec un cookie périmé, ou deux fois de suite, la
 * réponse est la même. Une déconnexion qui échoue est une session qui reste
 * ouverte sur un terminal partagé ; cette route n'échoue donc pas.
 */

import { NextResponse } from 'next/server';

import { logoutOps } from '@/lib/auth/auth';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function POST(): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  try {
    await logoutOps(correlationId);
  } catch {
    logger.warn('ops.logout.error', { correlationId });
  }
  return NextResponse.json(
    { success: true },
    { status: 200, headers: { 'Cache-Control': 'no-store' } },
  );
}
