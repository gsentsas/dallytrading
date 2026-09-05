import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { contexteErreur } from '@/lib/error-context';
import { logger, newCorrelationId } from '@/lib/logger';
import { activityEvent, fetchActivity } from '@/lib/ops/activity';

export const dynamic = 'force-dynamic';

const allowed = new Set(['date', 'cursor', 'limit', 'type', 'scope']);

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].some((key) => !allowed.has(key))) {
    return response({ success: false, error: 'Filtre invalide.' }, 400);
  }
  const limitText = url.searchParams.get('limit');
  const limit = limitText === null ? 25 : Number(limitText);
  const typeText = url.searchParams.get('type');
  const type = typeText === null ? undefined : activityEvent.safeParse(typeText).data;
  const scopeText = url.searchParams.get('scope');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100
      || (typeText !== null && type === undefined)
      || (scopeText !== null && scopeText !== 'mine' && scopeText !== 'team')) {
    return response({ success: false, error: 'Filtre invalide.' }, 400);
  }
  const session = await readOpsSession();
  if (!session) return response({ success: false, error: 'Session expirée.' }, 401);

  const correlation = newCorrelationId();
  const depart = Date.now();
  try {
    const data = await fetchActivity({
      limit,
      ...(url.searchParams.get('date') ? { date: url.searchParams.get('date')! } : {}),
      ...(url.searchParams.get('cursor') ? { cursor: url.searchParams.get('cursor')! } : {}),
      ...(type ? { type } : {}),
      ...(scopeText ? { scope: scopeText as 'mine' | 'team' } : {}),
    }, session.odooSessionId, correlation);
    return response({ success: true, data }, 200);
  } catch (error) {
    if (error instanceof OpsGatewayError && error.code === 'forbidden') {
      return response({ success: false, error: 'Session expirée.' }, 401);
    }
    if (error instanceof OpsGatewayError && error.code === 'invalid_request') {
      return response({ success: false, error: 'Filtre invalide.' }, 400);
    }
    logger.error('ops.activity.error', {
      correlationId: correlation,
      route: 'activity',
      durationMs: Date.now() - depart,
      ...contexteErreur(error),
    });
    return response({ success: false, error: 'Service momentanément indisponible.' }, 503);
  }
}

function response(body: unknown, status: number): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
}
