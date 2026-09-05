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
  /** Profondeur du chemin fautif. Un nombre : il ne peut rien citer. */
  readonly firstIssueDepth?: number;
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
 * - `error.name` — il s'écrit (`e.name = …`) et survit à `instanceof Error`.
 *   Un appelant peut donc y placer n'importe quel texte. Le type générique est
 *   donc la constante `'Error'` : moins précis, mais il ne cite rien.
 * - le chemin de l'anomalie Zod — avec `z.record` ou `.catchall`, un segment du
 *   chemin **est** une clé fournie par les données : `meta.<clé du client>`.
 *   Ce module est générique et servira d'autres schémas ; seule la profondeur
 *   sort, parce qu'un nombre ne peut rien citer.
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
        ? { firstIssueCode: premiere.code, firstIssueDepth: premiere.path.length }
        : {}),
    };
  }
  if (error instanceof Error) {
    return { errorClass: 'ERROR', errorType: 'Error' };
  }
  return { errorClass: 'UNKNOWN', errorType: 'UnknownError' };
}
