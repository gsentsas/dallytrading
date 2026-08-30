import { NextResponse } from 'next/server';
import { z } from 'zod';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { newCorrelationId } from '@/lib/logger';
import { prepareAppointmentReception } from '@/lib/ops/appointments';
import { reponseMutation } from '@/lib/ops/mutation-http';

/**
 * Ce que le navigateur envoie — et qui ne va pas plus loin.
 *
 * L'identifiant de demande sert au squelette de mutation, qui l'utilise pour
 * ne compter qu'une fois les reprises réseau d'un même geste. Il ne traverse
 * pas la passerelle : `prepare-reception` ne crée aucun objet métier, le
 * jeton client étant déjà idempotent par contrainte d'unicité. Il n'y a donc
 * rien à dédupliquer côté Odoo, et un registre de plus n'y stockerait que des
 * lignes qui n'empêchent rien.
 */
const corpsDuNavigateur = z.object({ request_uuid: z.string().uuid() }).strict();

export async function POST(request: Request, { params }: {
  params: Promise<{ reference: string }>;
}): Promise<NextResponse> {
  const reference = z.string().uuid().safeParse((await params).reference);
  if (!reference.success) return NextResponse.json({ success: false, error: 'Rendez-vous introuvable.' }, { status: 404 });
  const correlation = newCorrelationId();
  return reponseMutation({
    request, correlationId: correlation, origineAcceptable,
    lireSession: readOpsSession, schema: corpsDuNavigateur,
    evenement: 'ops.appointments.prepare-reception',
    executer: (_body, session) => prepareAppointmentReception(
      reference.data, session, correlation),
  });
}
