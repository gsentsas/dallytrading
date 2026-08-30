/**
 * Journal de Dally Ops.
 *
 * Une ligne JSON par événement, et jamais de contenu sensible : ni mot de
 * passe, ni identifiant de session, ni cookie, ni corps de requête. Ce qui est
 * journalisé sert à corréler et à mesurer, pas à rejouer.
 */

type Niveau = 'info' | 'warn' | 'error';

function ecrire(niveau: Niveau, message: string, contexte: Record<string, unknown> = {}): void {
  const ligne = JSON.stringify({
    timestamp: new Date().toISOString(),
    app: 'dally-ops',
    level: niveau,
    message,
    ...contexte,
  });
  if (niveau === 'error') console.error(ligne);
  else if (niveau === 'warn') console.warn(ligne);
  else console.log(ligne);
}

export const logger = {
  info: (message: string, contexte?: Record<string, unknown>) => ecrire('info', message, contexte),
  warn: (message: string, contexte?: Record<string, unknown>) => ecrire('warn', message, contexte),
  error: (message: string, contexte?: Record<string, unknown>) => ecrire('error', message, contexte),
};

/** Identifiant de corrélation, propagé jusqu'à Odoo. */
export function newCorrelationId(): string {
  return crypto.randomUUID();
}
