import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { newCorrelationId } from '@/lib/logger';
import { activityEvent, fetchIntakeActivity } from '@/lib/ops/activity';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  context: { readonly params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].some(
    (key) => key !== 'cursor' && key !== 'limit' && key !== 'type')) {
    return response({ success: false, error: 'Filtre invalide.' }, 400);
  }
  const limitText = url.searchParams.get('limit');
  const limit = limitText === null ? 25 : Number(limitText);
  const typeText = url.searchParams.get('type');
  const type = typeText === null ? undefined : activityEvent.safeParse(typeText).data;
  if (!Number.isInteger(limit) || limit < 1 || limit > 100
      || (typeText !== null && type === undefined)) {
    return response({ success: false, error: 'Filtre invalide.' }, 400);
  }
  const session = await readOpsSession();
  if (!session) return response({ success: false, error: 'Session expirée.' }, 401);
  const { reference } = await context.params;
  const correlation = newCorrelationId();
  try {
    const data = await fetchIntakeActivity(reference, {
      limit,
      ...(url.searchParams.get('cursor') ? { cursor: url.searchParams.get('cursor')! } : {}),
      ...(type ? { type } : {}),
    }, session.odooSessionId, correlation);
    return response({ success: true, data }, 200);
  } catch (error) {
    if (error instanceof OpsGatewayError && error.code === 'forbidden') {
      return response({ success: false, error: 'Session expirée.' }, 401);
    }
    if (error instanceof OpsGatewayError && error.code === 'not_found') {
      return response({ success: false, error: 'Dossier introuvable.' }, 404);
    }
    if (error instanceof OpsGatewayError && error.code === 'invalid_request') {
      return response({ success: false, error: 'Filtre invalide.' }, 400);
    }
    return response({ success: false, error: 'Service momentanément indisponible.' }, 503);
  }
}

function response(body: unknown, status: number): NextResponse {
  return NextResponse.json(body, {
    status,
    headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
}
