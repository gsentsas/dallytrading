/**
 * `GET /api/intakes/<reference>/legacy-detail` — lire un dossier repris.
 *
 * Une seule méthode est exportée. Il n'existe ni `POST`, ni `PUT`, ni
 * `PATCH`, ni `DELETE` : non pas refusés, mais absents. Un verbe déclaré puis
 * rejeté laisserait croire qu'il suffirait de lever le rejet.
 *
 * ## Pourquoi un plafond ici alors qu'Odoo garde déjà la porte
 *
 * Ce n'est pas une redite : celui d'Odoo protège la base, celui-ci protège la
 * session. Les références se devinent — `AIR-DSS-CDG-2026-002-A015` se compose
 * de tête — et une fiche est donc une surface d'énumération. Le compteur est
 * distinct de celui de la recherche : ce sont deux gestes du même comptoir, et
 * consulter beaucoup ne doit pas fermer la recherche.
 *
 * ## Ce que cette route ne journalise jamais
 *
 * Ni la référence demandée, ni le nom, ni le numéro, ni le contenu du dossier.
 * Le journal retient la corrélation, l'issue et la durée.
 */

import { NextResponse } from 'next/server';

import { readOpsSession } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { logger, newCorrelationId } from '@/lib/logger';
import { fetchLegacyIntake } from '@/lib/ops/legacy-intake';
import {
  OPS_LEGACY_DETAIL_IP,
  OPS_LEGACY_DETAIL_SESSION,
  checkRateLimit,
  cleLegacyDetailIp,
  cleLegacyDetailSession,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

const LONGUEUR_MAXIMALE = 120;

function reponse(corps: unknown, status: number, retryAfterSeconds = 0): NextResponse {
  const sortie = NextResponse.json(corps, {
    status,
    headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
  if (retryAfterSeconds > 0) sortie.headers.set('Retry-After', String(retryAfterSeconds));
  return sortie;
}

export async function GET(
  request: Request,
  contexte: { params: Promise<{ reference: string }> },
): Promise<NextResponse> {
  // Cette fiche ne se filtre pas : aucun paramètre n'a de sens ici, et en
  // accepter un ouvrirait une variante non contractée.
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].length > 0) {
    return reponse({ success: false, error: 'Filtre invalide.' }, 400);
  }

  const { reference: brute } = await contexte.params;
  const reference = decodeURIComponent(brute ?? '');
  if (!reference || reference.length > LONGUEUR_MAXIMALE) {
    return reponse({ success: false, error: 'Référence de dossier invalide.' }, 400);
  }

  const session = await readOpsSession();
  if (!session) return reponse({ success: false, error: 'Session expirée.' }, 401);

  // Le débit s'applique après la session : elle désigne le poste, et un
  // anonyme n'a pas à consommer le budget d'un opérateur.
  const cleSession = cleLegacyDetailSession(session.odooSessionId);
  const cleIp = cleLegacyDetailIp(getClientIp(request.headers));
  for (const [cle, budget] of [
    [cleSession, OPS_LEGACY_DETAIL_SESSION],
    [cleIp, OPS_LEGACY_DETAIL_IP],
  ] as const) {
    const etat = peekRateLimit(cle, budget.limite);
    if (!etat.allowed) {
      return reponse(
        { success: false, error: 'Trop de consultations. Réessayez dans quelques minutes.' },
        429, etat.retryAfterSeconds,
      );
    }
  }
  checkRateLimit(cleSession, OPS_LEGACY_DETAIL_SESSION.limite,
                 OPS_LEGACY_DETAIL_SESSION.fenetreMs);
  checkRateLimit(cleIp, OPS_LEGACY_DETAIL_IP.limite, OPS_LEGACY_DETAIL_IP.fenetreMs);

  const correlationId = newCorrelationId();
  const depart = Date.now();
  try {
    const data = await fetchLegacyIntake(reference, session.odooSessionId, correlationId);
    logger.info('ops.intakes.legacy_detail', {
      correlationId, durationMs: Date.now() - depart,
    });
    return reponse({ success: true, data }, 200);
  } catch (erreur) {
    const code = erreur instanceof OpsGatewayError ? erreur.code : 'error';
    if (code === 'forbidden') return reponse({ success: false, error: 'Session expirée.' }, 401);
    // Un dossier natif répond comme un dossier inexistant : le distinguer
    // renseignerait sur l'existence d'un dossier qu'on n'ouvre pas par ici.
    if (code === 'not_found') {
      return reponse({ success: false, error: 'Dossier introuvable.' }, 404);
    }
    if (code === 'invalid_request') {
      return reponse({ success: false, error: 'Référence de dossier invalide.' }, 400);
    }
    logger.error('ops.intakes.legacy_detail.error', {
      correlationId, code, durationMs: Date.now() - depart,
    });
    return reponse({ success: false, error: 'Service momentanément indisponible.' }, 503);
  }
}
