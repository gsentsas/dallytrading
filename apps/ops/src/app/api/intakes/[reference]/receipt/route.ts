/**
 * `GET /api/intakes/<reference>/receipt` — le reçu à afficher.
 *
 * Une lecture, jamais une écriture : demander un reçu ne crée ni facture, ni
 * paiement, ni numéro de dossier. Le client affiché vient du dossier, et le
 * navigateur ne le désigne d'aucune manière.
 *
 * `no-store` : ce document nomme une personne et dit ce qu'elle a payé. Ni le
 * navigateur, ni un proxy partagé, ni le Service Worker ne doivent en garder
 * une copie que le porteur suivant du téléphone retrouverait.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchReceipt } from '@/lib/ops/receipts';
import { logger, newCorrelationId } from '@/lib/logger';

export const dynamic = 'force-dynamic';

const SANS_CACHE = {
  'Cache-Control': 'private, no-store, max-age=0',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
} as const;

function erreur(status: number, message: string, code?: string) {
  return NextResponse.json(
    code ? { success: false, error: message, code } : { success: false, error: message },
    { status, headers: SANS_CACHE },
  );
}

export async function GET(
  _request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');

  const { reference } = await contexte.params;
  try {
    const receipt = await fetchReceipt(reference, session.odooSessionId, correlationId);
    return NextResponse.json(
      { success: true, data: { receipt } },
      { status: 200, headers: SANS_CACHE },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found' || code === 'invalid_request') {
      return erreur(404, 'Dossier introuvable.');
    }
    if (code === 'conflict') {
      return erreur(409, 'Ce dossier est annulé : aucun reçu ne peut être remis.',
                    'intake_cancelled');
    }
    logger.error('ops.receipt.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}
