/**
 * Ce qu'on a le droit d'écrire dans le journal à propos d'une erreur.
 *
 * Un `catch` qui retombe sur 503 ne dit rien de ce qui a cassé : la passerelle
 * Odoo, un délai dépassé, une réponse hors contrat, ou autre chose. Répondre en
 * journalisant l'erreur entière serait pire : le message d'une `ZodError` cite
 * la valeur reçue, et la valeur reçue est de la donnée client.
 *
 * Ce module tranche une fois pour toutes ce qui sort : la **forme** de l'erreur,
 * jamais son **contenu**. Rien ici ne peut porter un nom de client, un montant,
 * une référence de dossier ni un identifiant de session — non parce qu'on filtre
 * après coup, mais parce qu'aucun champ recopié n'est d'origine métier.
 */
import { ZodError } from 'zod';

import { OpsGatewayError } from '@/lib/auth/odoo-ops';

export type ClasseErreur = 'OPS_GATEWAY' | 'VALIDATION' | 'ERROR' | 'UNKNOWN';

export interface ContexteErreur {
  readonly errorClass: ClasseErreur;
  readonly errorType: string;
  /** Le code de refus de la passerelle : une union fermée de littéraux. */
  readonly gatewayCode?: string;
  readonly issueCount?: number;
  /** Code d'anomalie Zod (`invalid_type`, `too_small`…), jamais une valeur. */
  readonly firstIssueCode?: string;
  /** Chemin dans le schéma (`events.0.summary`) : des noms de champs à nous. */
  readonly firstIssuePath?: string;
}

/**
 * Décrit une erreur sans la citer.
 *
 * `OpsGatewayError` d'abord, `ZodError` ensuite : toutes deux héritent d'`Error`
 * et seraient sinon avalées par le cas générique.
 *
 * Ce qui est délibérément absent :
 *
 * - `error.message` — celui d'une `ZodError` contient la valeur rejetée, et
 *   celui d'une erreur générique n'est contraint par rien.
 * - `error.stack` — les cadres peuvent porter des arguments.
 * - `conflictCode` d'`OpsGatewayError` — c'est un code stable côté Odoo, mais
 *   son contenu n'est pas une union fermée côté TypeScript. Tant que rien ne le
 *   prouve, il reste dehors.
 * - `issue.received` / `issue.expected` — la valeur reçue, précisément.
 */
export function contexteErreur(error: unknown): ContexteErreur {
  if (error instanceof OpsGatewayError) {
    return {
      errorClass: 'OPS_GATEWAY',
      errorType: 'OpsGatewayError',
      gatewayCode: error.code,
    };
  }
  if (error instanceof ZodError) {
    const premiere = error.issues[0];
    return {
      errorClass: 'VALIDATION',
      errorType: 'ZodError',
      issueCount: error.issues.length,
      ...(premiere
        ? {
            firstIssueCode: premiere.code,
            firstIssuePath: premiere.path.map((cle) => String(cle)).join('.'),
          }
        : {}),
    };
  }
  if (error instanceof Error) {
    return { errorClass: 'ERROR', errorType: error.name };
  }
  return { errorClass: 'UNKNOWN', errorType: 'UnknownError' };
}
