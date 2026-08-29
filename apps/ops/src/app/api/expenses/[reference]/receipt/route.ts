/**
 * `POST /api/expenses/<reference>/receipt` — joindre la photo d'un ticket.
 *
 * La seule route de Dally Ops qui reçoive autre chose que du JSON. Elle
 * n'emprunte donc pas `reponseMutation`, mais applique les mêmes cinq
 * contrôles dans le même ordre : origine, session, forme, débit, traduction
 * des refus. Les deux chemins doivent rester lisibles côte à côte.
 *
 * Ce qu'elle ne fait jamais : mettre la photo dans l'URL, la journaliser, ou
 * défaire la dépense quand l'envoi échoue.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { origineAcceptable } from '@/lib/http/origine';
import { attachReceipt, TAILLE_MAXIMALE_JUSTIFICATIF } from '@/lib/ops/expenses';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  OPS_JUSTIFICATIF_IP,
  OPS_JUSTIFICATIF_SESSION,
  checkRateLimit,
  cleJustificatifDemande,
  cleJustificatifIp,
  cleJustificatifSession,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Ce que l'appareil photo d'un téléphone produit. */
const TYPES_ANNONCES = new Set([
  'image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif',
]);

/**
 * Les messages lus par l'opérateur, indexés par le code du refus.
 *
 * Le message d'Odoo n'est jamais relayé tel quel : c'est le BFF qui décide de
 * ce que le terrain lit, et un refus doit dire quoi faire — reprendre la
 * photo, la réduire, appeler un responsable.
 */
const MESSAGES: Record<string, string> = {
  receipt_missing: 'Aucune photo n’a été reçue.',
  receipt_empty: 'La photo reçue est vide. Reprenez-la.',
  receipt_too_large: 'La photo dépasse 10 Mo. Reprenez-la en qualité réduite.',
  receipt_type_not_allowed:
    'Seules les photos JPEG, PNG, WebP ou HEIC sont acceptées comme justificatif.',
  receipt_already_attached:
    'Cette dépense a déjà un justificatif. Il ne peut pas être remplacé depuis le terrain.',
  idempotency_conflict:
    'Cet envoi a déjà été traité avec une autre photo.',
  default: 'La photo n’a pas pu être enregistrée.',
};

function erreur(status: number, message: string, code?: string, retryAfter = 0) {
  const reponse = NextResponse.json(
    code ? { success: false, error: message, code } : { success: false, error: message },
    { status },
  );
  if (retryAfter > 0) reponse.headers.set('Retry-After', String(retryAfter));
  reponse.headers.set('Cache-Control', 'no-store');
  return reponse;
}

export async function POST(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const { reference } = await contexte.params;
  const depart = Date.now();

  if (!origineAcceptable(request)) return erreur(403, 'Requête refusée.');
  if (!(request.headers.get('content-type') ?? '').includes('multipart/form-data')) {
    return erreur(415, 'Requête refusée.');
  }

  const session = await readOpsSession();
  if (!session) return erreur(401, 'Session expirée.');

  let formulaire: FormData;
  try {
    formulaire = await request.formData();
  } catch {
    return erreur(400, 'Requête invalide.');
  }

  const requestUuid = formulaire.get('request_uuid');
  if (typeof requestUuid !== 'string' || !UUID.test(requestUuid)) {
    return erreur(400, 'Requête invalide.');
  }
  const fichier = formulaire.get('receipt');
  if (!(fichier instanceof File) || fichier.size === 0) {
    return erreur(422, MESSAGES['receipt_missing'] ?? '', 'receipt_missing');
  }
  if (fichier.size > TAILLE_MAXIMALE_JUSTIFICATIF) {
    return erreur(422, MESSAGES['receipt_too_large'] ?? '', 'receipt_too_large');
  }
  // Le type annoncé n'est qu'un premier tri : Odoo tranche sur les octets. On
  // le vérifie tout de même pour ne pas transporter un PDF de dix mégaoctets
  // jusqu'au serveur pour qu'il le refuse.
  if (!TYPES_ANNONCES.has(fichier.type)) {
    return erreur(422, MESSAGES['receipt_type_not_allowed'] ?? '',
                  'receipt_type_not_allowed');
  }

  const cleSession = cleJustificatifSession(session.odooSessionId);
  const cleIp = cleJustificatifIp(getClientIp(request.headers));
  for (const [cle, budget, portee] of [
    [cleSession, OPS_JUSTIFICATIF_SESSION, 'session'],
    [cleIp, OPS_JUSTIFICATIF_IP, 'ip'],
  ] as const) {
    const etat = peekRateLimit(cle, budget.limite);
    if (!etat.allowed) {
      logger.warn('ops.expense.receipt.throttled', { correlationId, scope: portee });
      return erreur(429, 'Trop d’envois. Réessayez dans quelques minutes.',
                    undefined, etat.retryAfterSeconds);
    }
  }
  // Les reprises réseau d'un même envoi ne comptent qu'une fois.
  const premiere = checkRateLimit(
    cleJustificatifDemande(requestUuid), 1, OPS_JUSTIFICATIF_SESSION.fenetreMs);
  if (premiere.allowed) {
    checkRateLimit(cleSession, OPS_JUSTIFICATIF_SESSION.limite,
                   OPS_JUSTIFICATIF_SESSION.fenetreMs);
    checkRateLimit(cleIp, OPS_JUSTIFICATIF_IP.limite, OPS_JUSTIFICATIF_IP.fenetreMs);
  }

  try {
    const data = await attachReceipt(
      reference,
      requestUuid,
      { nom: fichier.name, type: fichier.type, contenu: fichier },
      session.odooSessionId,
      correlationId,
    );
    // Ni le nom du fichier, ni sa taille, ni son type : un justificatif est
    // une pièce comptable, pas une ligne de journal applicatif.
    logger.info('ops.expense.receipt', { correlationId, durationMs: Date.now() - depart });
    return NextResponse.json(
      { success: true, data },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (e) {
    const code = e instanceof OpsGatewayError ? e.code : 'error';
    const refus = e instanceof OpsGatewayError ? (e.conflictCode ?? 'default') : 'default';
    if (code === 'forbidden') return erreur(401, 'Session expirée.');
    if (code === 'not_found') return erreur(404, 'Dépense introuvable.');
    if (code === 'invalid_request') return erreur(400, 'Requête invalide.');
    if (code === 'unprocessable') {
      logger.warn('ops.expense.receipt.rejected', { correlationId, code: refus });
      return erreur(422, MESSAGES[refus] ?? MESSAGES['default'] ?? '', refus);
    }
    if (code === 'conflict') {
      logger.warn('ops.expense.receipt.conflict', { correlationId, code: refus });
      return erreur(409, MESSAGES[refus] ?? MESSAGES['default'] ?? '', refus);
    }
    logger.error('ops.expense.receipt.error', { correlationId, code });
    return erreur(503, 'Service momentanément indisponible.');
  }
}
