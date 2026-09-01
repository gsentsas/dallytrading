/**
 * `GET|DELETE /api/intakes/<reference>/photos/<photoUuid>` — une preuve.
 *
 * ## La lecture ne bufferise rien
 *
 * Le corps traverse le BFF en flux. Une image de dix mébioctets ne coûte donc
 * pas dix mébioctets de mémoire par lecteur simultané, et un opérateur qui
 * ferme l'écran interrompt réellement la lecture chez Odoo au lieu de la
 * laisser finir dans le vide.
 *
 * ## Les en-têtes sont reposés, jamais relayés
 *
 * Rien de ce qu'Odoo renvoie n'est transmis tel quel : ni cookie, ni `Server`,
 * ni `ETag`. Seuls les quatre en-têtes qui décident de la sécurité d'affichage
 * sont écrits ici, avec leurs valeurs choisies.
 *
 * ## Pourquoi le retrait emprunte le squelette commun
 *
 * C'est une mutation JSON portant un `request_uuid` : exactement ce que
 * `reponseMutation` sait faire. Réécrire ses cinq contrôles pour cette route
 * reviendrait à en oublier un.
 */

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { logger, newCorrelationId } from '@/lib/logger';
import { deletePhoto, readPhotoBinary } from '@/lib/ops/photos';
import { reponseMutation } from '@/lib/ops/mutation-http';

export const dynamic = 'force-dynamic';

export const demandeRetrait = z.object({
  request_uuid: z.string().uuid(),
}).strict();

/**
 * Ce que le navigateur reçoit avec les octets.
 *
 * `nosniff` empêche un rendu en HTML d'un fichier dont le type a pourtant été
 * validé sur ses octets ; la CSP ferme tout le reste — aucune ressource, aucun
 * script, aucun cadre. `inline` parce que l'écran affiche la preuve au lieu de
 * la télécharger.
 */
const EN_TETES_IMAGE: Readonly<Record<string, string>> = {
  'Cache-Control': 'private, no-store',
  'X-Content-Type-Options': 'nosniff',
  'Content-Disposition': 'inline',
  'Content-Security-Policy': "default-src 'none'; img-src 'self' data:; sandbox",
  'Referrer-Policy': 'no-referrer',
};

function erreur(status: number, message: string) {
  return NextResponse.json(
    { success: false, error: message },
    { status, headers: { 'Cache-Control': 'no-store' } },
  );
}

export async function GET(
  request: Request,
  contexte: { params: Promise<{ reference: string; photoUuid: string }> },
): Promise<Response> {
  const correlationId = newCorrelationId();
  const { reference, photoUuid } = await contexte.params;

  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');

  try {
    const image = await readPhotoBinary(
      decodeURIComponent(reference),
      decodeURIComponent(photoUuid),
      session.odooSessionId,
      correlationId,
    );
    return new Response(image.corps, {
      status: 200,
      headers: { ...EN_TETES_IMAGE, 'Content-Type': image.type },
    });
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found') return erreur(404, 'Photo introuvable.');
    logger.error('ops.photos.read.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}

export async function DELETE(
  request: Request,
  contexte: { params: Promise<{ reference: string; photoUuid: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference, photoUuid } = await contexte.params;
  return reponseMutation({
    request,
    correlationId,
    origineAcceptable,
    lireSession: readOpsSession,
    schema: demandeRetrait,
    evenement: 'ops.photos.deleted',
    executer: (demande, sessionId) =>
      deletePhoto(
        decodeURIComponent(reference),
        decodeURIComponent(photoUuid),
        demande.request_uuid,
        sessionId,
        correlationId,
      ),
  });
}
