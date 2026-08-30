/**
 * `POST /api/auth/login` — ouverture de session d'un opérateur.
 *
 * Le mot de passe entre ici, part vers Odoo, et disparaît. Il n'est pas
 * journalisé, pas conservé, pas placé dans le cookie.
 */

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { MESSAGE_ECHEC_CONNEXION, loginOps } from '@/lib/auth/auth';
import { OpsGatewayError } from '@/lib/auth/odoo-ops';
import { logger, newCorrelationId } from '@/lib/logger';
import {
  OPS_LOGIN_IP,
  OPS_LOGIN_UTILISATEUR,
  checkRateLimit,
  cleLoginIp,
  cleLoginUtilisateur,
  clearRateLimitKey,
  getClientIp,
  peekRateLimit,
} from '@/lib/rate-limit';

export const dynamic = 'force-dynamic';

const schema = z.object({
  login: z.string().trim().min(1).max(128),
  password: z.string().min(1).max(256),
});

/** Toujours la même réponse, quel que soit le motif du refus. */
function refus(status = 401, retryAfterSeconds = 0): NextResponse {
  const reponse = NextResponse.json(
    { success: false, error: MESSAGE_ECHEC_CONNEXION },
    { status },
  );
  if (retryAfterSeconds > 0) {
    reponse.headers.set('Retry-After', String(retryAfterSeconds));
  }
  reponse.headers.set('Cache-Control', 'no-store');
  return reponse;
}

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();

  // Un formulaire d'un autre site ne peut pas émettre `application/json` sans
  // requête préalable CORS. Exiger ce type ferme la porte au CSRF par
  // formulaire, en plus du `SameSite=Lax` du cookie.
  const type = request.headers.get('content-type') ?? '';
  if (!type.includes('application/json')) return refus(415);

  // Comme celui du compte, ce budget compte les échecs : tous les téléphones
  // d'un entrepôt sortent par la même adresse publique, et compter les
  // requêtes verrouillerait l'équipe parce qu'elle travaille.
  const cleIp = cleLoginIp(getClientIp(request.headers));
  const budgetIp = peekRateLimit(cleIp, OPS_LOGIN_IP.limite);
  if (!budgetIp.allowed) {
    logger.warn('ops.login.throttled', { correlationId, scope: 'ip' });
    return refus(429, budgetIp.retryAfterSeconds);
  }

  let corps: unknown;
  try {
    corps = await request.json();
  } catch {
    return refus(400);
  }

  const analyse = schema.safeParse(corps);
  if (!analyse.success) return refus(400);
  const { login, password } = analyse.data;

  // Le budget du compte compte les ÉCHECS : on le consulte ici, on ne le
  // consomme qu'en cas de refus. Un poste d'entrepôt sert plusieurs
  // opérateurs dans la journée ; verrouiller un compte parce qu'il s'est
  // connecté avec succès serait un déni de service qu'on s'infligerait.
  const cleCompte = cleLoginUtilisateur(login);
  const budgetCompte = peekRateLimit(cleCompte, OPS_LOGIN_UTILISATEUR.limite);
  if (!budgetCompte.allowed) {
    logger.warn('ops.login.throttled', { correlationId, scope: 'account' });
    return refus(429, budgetCompte.retryAfterSeconds);
  }

  try {
    const identite = await loginOps(login, password, correlationId);
    clearRateLimitKey(cleCompte);
    const reponse = NextResponse.json({ success: true, data: identite });
    reponse.headers.set('Cache-Control', 'no-store');
    return reponse;
  } catch (erreur) {
    if (erreur instanceof OpsGatewayError) {
      if (erreur.code === 'invalid_credentials') {
        checkRateLimit(cleCompte, OPS_LOGIN_UTILISATEUR.limite, OPS_LOGIN_UTILISATEUR.fenetreMs);
        // L'adresse ne se relâche pas sur une réussite, elle : sinon un
        // balayage se remettrait à zéro en intercalant une connexion valide.
        checkRateLimit(cleIp, OPS_LOGIN_IP.limite, OPS_LOGIN_IP.fenetreMs);
        return refus(401);
      }
      // Odoo indisponible : le message reste générique, mais le statut dit la
      // vérité pour que le poste terrain distingue « c'est moi » de « c'est
      // le serveur » et puisse réessayer.
      logger.error('ops.login.unavailable', { correlationId, code: erreur.code });
      return NextResponse.json(
        { success: false, error: 'Service momentanément indisponible.' },
        { status: 503, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    logger.error('ops.login.error', { correlationId });
    return refus(500);
  }
}
