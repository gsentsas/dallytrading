/** `GET /api/expense-consolidations` — les départs ouverts aux dépenses. */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchExpenseConsolidations } from '@/lib/ops/expenses';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const session = await readOpsSession();
  if (!session) {
    return NextResponse.json(
      { success: false, error: 'Session expirée.' },
      { status: 401, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  try {
    const consolidations = await fetchExpenseConsolidations(
      session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: { consolidations } },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (erreur) {
    const code = erreur instanceof OpsGatewayError ? erreur.code : 'error';
    if (code === 'forbidden') {
      return NextResponse.json(
        { success: false, error: 'Session expirée.' },
        { status: 401, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.expense.consolidations.error', { correlationId, code });
    return NextResponse.json(
      { success: false, error: 'Service momentanément indisponible.' },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
