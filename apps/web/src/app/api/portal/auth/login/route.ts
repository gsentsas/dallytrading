/**
 * POST /api/portal/auth/login
 *
 * Le seul endroit du frontend qui voit un mot de passe client. Il traverse ce
 * handler et le corps de la requête vers Odoo, puis disparaît : ni journalisé, ni
 * stocké, ni renvoyé.
 *
 * ## Ce que le handler établit, et ce qu'il n'établit pas
 *
 * Il établit qu'Odoo a accepté les identifiants ET que le compte est bien un
 * compte portail. Il n'établit aucun droit : rien ici ne décide de ce que le
 * client pourra lire. Ce sont les record rules Odoo qui le décident, à chaque
 * requête, sous l'identité de la session.
 */

import type { NextResponse } from 'next/server';

import { loginPortal } from '@/lib/portal/auth';
import { PortalGatewayError } from '@/lib/portal/odoo-portal';
import { checkOrigin } from '@/lib/portal/csrf';
import { getServerEnv } from '@/lib/env';
import { logger, newCorrelationId } from '@/lib/logger';
import { checkRateLimit, getClientIp } from '@/lib/rate-limit';
import { portalError, portalJson } from '../../_shared';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Deux compteurs, deux cibles différentes.
 *
 * Par IP : freine un script qui balaye des identifiants depuis une machine.
 * Par identifiant : freine une attaque distribuée qui vise UN compte connu — que
 * le compteur par IP ne verrait jamais, puisque chaque tentative vient d'ailleurs.
 *
 * ⚠️ Limite réelle, à ne pas surestimer : `checkRateLimit` compte en mémoire d'un
 * seul processus Node. Il ne coordonne rien entre processus et repart de zéro à
 * chaque redémarrage. Ce n'est donc PAS une protection distribuée contre le
 * bourrage d'identifiants — c'est un frein qui arrête le cas courant. Une vraie
 * protection volumétrique se place devant Node (nginx `limit_req`, qui exige un
 * `limit_req_zone` hors de portée des directives Plesk par domaine — cf.
 * docs/DEPLOYMENT.md).
 */
const IP_LIMIT = 10;
const LOGIN_LIMIT = 5;
const RATE_WINDOW_MS = 5 * 60_000;

/** Bornes de forme. Un corps hors gabarit est rejeté sans toucher à Odoo. */
const MAX_BODY_BYTES = 4 * 1024;
const MAX_LOGIN_LENGTH = 254;
const MAX_PASSWORD_LENGTH = 256;

/**
 * Message unique pour tous les échecs d'identification.
 *
 * Identifiant inconnu, mot de passe faux, compte interne, compte désactivé :
 * même texte, même code, même statut. Distinguer les cas transformerait le
 * formulaire en oracle d'existence de comptes.
 */
const GENERIC_FAILURE =
  'Identifiants invalides. Vérifiez votre adresse e-mail et votre mot de passe.';

export async function POST(request: Request): Promise<NextResponse> {
  const correlationId = newCorrelationId();
  const clientIp = getClientIp(request.headers);

  const origin = checkOrigin(
    request.headers, getServerEnv().NEXT_PUBLIC_SITE_URL,
  );
  if (!origin.ok) {
    logger.warn('Portal login refused: bad origin', {
      correlationId, clientIp, reason: origin.reason,
    });
    return portalError(403, 'forbidden', 'Requête refusée.', correlationId);
  }

  const byIp = checkRateLimit(`portal:login:ip:${clientIp}`, IP_LIMIT, RATE_WINDOW_MS);
  if (!byIp.allowed) {
    logger.warn('Portal login rate limited (ip)', { correlationId, clientIp });
    return portalError(
      429, 'rate_limited',
      'Trop de tentatives. Merci de patienter quelques minutes.',
      correlationId, { 'Retry-After': String(byIp.retryAfterSeconds) },
    );
  }

  if (Number(request.headers.get('content-length') ?? '0') > MAX_BODY_BYTES) {
    return portalError(413, 'payload_too_large', 'Requête trop volumineuse.', correlationId);
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return portalError(400, 'invalid_body', 'Requête invalide.', correlationId);
  }

  const login = typeof (body as { login?: unknown })?.login === 'string'
    ? ((body as { login: string }).login).trim()
    : '';
  const password = typeof (body as { password?: unknown })?.password === 'string'
    ? (body as { password: string }).password
    : '';

  if (
    login.length === 0 || login.length > MAX_LOGIN_LENGTH ||
    password.length === 0 || password.length > MAX_PASSWORD_LENGTH
  ) {
    // Même réponse qu'un échec d'authentification : un 400 distinct dirait au
    // moins quelle forme d'entrée est acceptée.
    return portalError(401, 'invalid_credentials', GENERIC_FAILURE, correlationId);
  }

  const byLogin = checkRateLimit(
    `portal:login:user:${login.toLowerCase()}`, LOGIN_LIMIT, RATE_WINDOW_MS,
  );
  if (!byLogin.allowed) {
    logger.warn('Portal login rate limited (login)', { correlationId, clientIp });
    return portalError(
      429, 'rate_limited',
      'Trop de tentatives. Merci de patienter quelques minutes.',
      correlationId, { 'Retry-After': String(byLogin.retryAfterSeconds) },
    );
  }

  try {
    const identity = await loginPortal(login, password, correlationId);
    // Aucun identifiant, aucune adresse : de quoi corréler, rien de plus.
    logger.info('Portal login succeeded', { correlationId, clientIp });
    // DTO minimal. Il sert à afficher « Bonjour X » et rien d'autre : aucune
    // décision de sécurité ne s'appuie sur ce que le navigateur en fait.
    return portalJson({ name: identity.name, company: identity.company });
  } catch (error) {
    if (error instanceof PortalGatewayError) {
      if (error.code === 'unavailable' || error.code === 'timeout') {
        logger.error('Portal login unavailable', { correlationId, code: error.code });
        return portalError(
          503, 'unavailable',
          'Le service est momentanément indisponible. Merci de réessayer dans quelques instants.',
          correlationId,
        );
      }
      logger.warn('Portal login failed', { correlationId, clientIp, code: error.code });
      return portalError(401, 'invalid_credentials', GENERIC_FAILURE, correlationId);
    }
    logger.error('Portal login unexpected error', { correlationId });
    return portalError(
      503, 'unavailable', 'Le service est momentanément indisponible.', correlationId,
    );
  }
}
