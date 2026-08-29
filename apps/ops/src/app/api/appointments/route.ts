import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { newCorrelationId } from '@/lib/logger';
import {
  appointmentCreateRequest, appointmentRange, createAppointment,
  fetchAppointments,
} from '@/lib/ops/appointments';
import { agendaRead } from '@/lib/ops/agenda-http';
import { reponseMutation } from '@/lib/ops/mutation-http';

export const dynamic = 'force-dynamic';

export async function GET(request: Request): Promise<NextResponse> {
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].some((key) => key !== 'from' && key !== 'to')) {
    return NextResponse.json(
      { success: false, error: 'Plage invalide.' }, { status: 400 });
  }
  const parsed = appointmentRange.safeParse({
    from: url.searchParams.get('from'), to: url.searchParams.get('to'),
  });
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: 'Plage invalide.' }, { status: 400 });
  }
  const correlation = newCorrelationId();
  return agendaRead(request, (session) => fetchAppointments(
    parsed.data, session, correlation,
  ));
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlation = newCorrelationId();
  return reponseMutation({
    request, correlationId: correlation, origineAcceptable,
    lireSession: readOpsSession, schema: appointmentCreateRequest,
    evenement: 'ops.appointments.create',
    executer: (body, session) => createAppointment(body, session, correlation),
  });
}
