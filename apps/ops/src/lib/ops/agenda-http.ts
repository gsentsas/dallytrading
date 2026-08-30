import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import {
  checkRateLimit, cleRechercheIp, cleRechercheSession, getClientIp,
} from '@/lib/rate-limit';

const WINDOW = 5 * 60_000;

export async function agendaRead(
  request: Request,
  execute: (sessionId: string) => Promise<unknown>,
): Promise<NextResponse> {
  if (!origineAcceptable(request)) {
    return NextResponse.json(
      { success: false, error: 'Requête refusée.' }, { status: 403 });
  }
  const session = await readOpsSession();
  if (!session) {
    return NextResponse.json(
      { success: false, error: 'Session expirée.' }, { status: 401 });
  }
  const limits = [
    [`ops:agenda:${cleRechercheSession(session.odooSessionId)}`, 120],
    [`ops:agenda:${cleRechercheIp(getClientIp(request.headers))}`, 600],
  ] as const;
  if (limits.some(([key, limit]) => !checkRateLimit(key, limit, WINDOW).allowed)) {
    return NextResponse.json(
      { success: false, error: 'Trop de consultations.' }, { status: 429 });
  }
  try {
    return NextResponse.json(
      { success: true, data: await execute(session.odooSessionId) },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    const gateway = error instanceof OpsGatewayError ? error : null;
    if (gateway?.code === 'forbidden') {
      return NextResponse.json(
        { success: false, error: 'Session expirée.' }, { status: 401 });
    }
    if (gateway?.code === 'not_found') {
      return NextResponse.json(
        { success: false, error: 'Rendez-vous introuvable.' }, { status: 404 });
    }
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503 },
    );
  }
}
