/**
 * `POST /api/intakes/<reference>/state` — faire avancer un dossier.
 *
 * Le navigateur ne joint jamais Odoo. Il poste ici ; le serveur relit le
 * cookie, présente la session de l'opérateur et traduit la décision d'Odoo —
 * y compris son refus, qui est une information métier et non une panne.
 *
 * ## Pourquoi rien n'est écrit ici
 *
 * Origine, type de contenu, session, contrat strict, débit par session et par
 * adresse, geste rejoué compté une seule fois, traduction des refus : ces
 * contrôles appartiennent au squelette commun des mutations. Les réécrire
 * pour cette route, c'était en oublier un — et c'est bien le débit qui
 * manquait.
 *
 * ## Ce que cette route ne journalise jamais
 *
 * Ni le corps, ni la référence, ni l'identifiant du geste. Le journal retient
 * la corrélation, l'issue et la durée.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { origineAcceptable } from '@/lib/http/origine';
import { newCorrelationId } from '@/lib/logger';
import { advanceIntakeState, demandeTransition } from '@/lib/ops/intake-state';
import { reponseMutation } from '@/lib/ops/mutation-http';

export const dynamic = 'force-dynamic';

export async function POST(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  return reponseMutation({
    request,
    correlationId,
    origineAcceptable,
    lireSession: readOpsSession,
    schema: demandeTransition,
    evenement: 'ops.intakes.state',
    executer: (demande, sessionId) =>
      advanceIntakeState(
        decodeURIComponent(reference),
        demande,
        sessionId,
        correlationId,
      ),
  });
}
