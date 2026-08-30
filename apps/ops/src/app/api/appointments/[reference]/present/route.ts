import { NextResponse } from 'next/server';
import { z } from 'zod';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { newCorrelationId } from '@/lib/logger';
import { appointmentAction, appointmentActionRequest } from '@/lib/ops/appointments';
import { reponseMutation } from '@/lib/ops/mutation-http';

export async function POST(request: Request, { params }: {
  params: Promise<{ reference: string }>;
}): Promise<NextResponse> {
  const reference = z.string().uuid().safeParse((await params).reference);
  if (!reference.success) return NextResponse.json({ success: false, error: 'Rendez-vous introuvable.' }, { status: 404 });
  const correlation = newCorrelationId();
  return reponseMutation({
    request, correlationId: correlation, origineAcceptable,
    lireSession: readOpsSession, schema: appointmentActionRequest,
    evenement: 'ops.appointments.present',
    executer: (body, session) => appointmentAction(
      reference.data, 'present', body.request_uuid, session, correlation),
  });
}
