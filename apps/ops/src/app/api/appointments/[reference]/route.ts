import { NextResponse } from 'next/server';
import { z } from 'zod';

import { newCorrelationId } from '@/lib/logger';
import { fetchAppointment } from '@/lib/ops/appointments';
import { agendaRead } from '@/lib/ops/agenda-http';

export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const reference = z.string().uuid().safeParse((await params).reference);
  if (!reference.success) {
    return NextResponse.json(
      { success: false, error: 'Rendez-vous introuvable.' }, { status: 404 });
  }
  const correlation = newCorrelationId();
  return agendaRead(request, (session) => fetchAppointment(
    reference.data, session, correlation,
  ));
}
