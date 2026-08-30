/**
 * `GET /api/intakes/<reference>/receipt/pdf` — le reçu à remettre.
 *
 * Les octets traversent le BFF ; l'adresse d'Odoo n'est jamais donnée au
 * navigateur. Il n'existe donc aucune URL publique devinable menant au reçu
 * d'un client : la session décide, comme pour tout le reste.
 *
 * Le nom du fichier ne porte pas le nom du client. Un téléphone de terrain
 * passe de main en main, et une liste de téléchargements en dirait trop.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { fetchReceiptPdf } from '@/lib/ops/receipts';
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
    const { contenu, nomFichier } = await fetchReceiptPdf(
      reference, session.odooSessionId, correlationId,
    );
    return new NextResponse(contenu, {
      status: 200,
      headers: {
        ...SANS_CACHE,
        'Content-Type': 'application/pdf',
        'Content-Length': String(contenu.byteLength),
        'Content-Disposition': `attachment; filename="${nomFichier}"`,
      },
    }) as NextResponse;
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
    logger.error('ops.receipt.pdf.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}
