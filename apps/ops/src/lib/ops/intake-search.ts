/**
 * Le contrat de la recherche de dossier.
 *
 * ## Ce que `reference` désigne, et pourquoi c'est la seule clé
 *
 * `reference` est toujours la référence **globale** du dossier. `A001` est
 * local à son départ : deux consolidations en ont chacune un, et composer une
 * URL avec lui ouvrirait le dossier d'un autre client. `local_reference`
 * existe pour l'œil de l'opérateur, jamais pour un lien.
 *
 * ## Pourquoi `detail_access` vient du serveur
 *
 * La fiche Ops ne sait afficher que les dossiers nés de Dally Ops. Savoir si
 * un dossier trouvé s'ouvrira demande le domaine exact de cette fiche —
 * société, origine, consolidation d'entrée. Le reconstituer ici en dupliquerait
 * la règle, et la copie divergerait au premier changement. Odoo décide ; ce
 * module ne fait que refuser ce qu'il ne reconnaît pas.
 */

import { z } from 'zod';

import { opsGetQuery } from '@/lib/auth/odoo-ops';

export const intakeSearchItem = z.object({
  /**
   * La référence globale — la seule clé de navigation.
   *
   * Elle peut être **vide** : des dossiers repris n'en portent aucune, et le
   * serveur les rend tout de même, avec `detail_access: "unavailable"`. Exiger
   * ici au moins un caractère faisait tomber la page entière sur un tel
   * résultat, alors qu'un seul dossier était concerné. C'est `detail_access`
   * qui dit si le dossier s'ouvre, pas la longueur de sa référence.
   */
  reference: z.string().max(120),
  /** `A001`, pour l'œil. Vide sur un dossier repris du classeur. */
  local_reference: z.string().max(40),
  customer_name: z.string().max(200),
  customer_phone: z.string().max(60),
  state: z.string().max(40),
  transport_mode: z.string().max(20),
  consolidation_reference: z.string().max(120),
  received_on: z.string().max(30),
  /**
   * Trois issues, décidées par le serveur : `full` ouvre la fiche complète,
   * `readonly` la fiche en lecture seule d'un dossier repris, `unavailable`
   * n'ouvre rien — faute d'une référence globale, aucune URL ne saurait
   * désigner le dossier sans risquer celui d'un autre client.
   */
  detail_access: z.enum(['full', 'readonly', 'unavailable']),
  detail_access_reason: z
    .enum(['legacy_readonly', 'no_reference'])
    .nullable(),
}).strict();

/**
 * Une page, et un drapeau.
 *
 * Pas de curseur : il faudrait une clé de parcours, et la seule qui soit
 * totale est `dally.shipment.id` — un identifiant de base, qui n'a rien à
 * faire dans le navigateur. `.strict()` refuse d'ailleurs qu'un curseur
 * réapparaisse un jour sans décision.
 */
export const intakeSearchPage = z.object({
  items: z.array(intakeSearchItem).max(50),
  has_more: z.boolean(),
}).strict();

export type IntakeSearchItem = z.infer<typeof intakeSearchItem>;
export type IntakeSearchPage = z.infer<typeof intakeSearchPage>;

export interface IntakeSearchQuery {
  readonly q: string;
  readonly limit?: number;
}

/**
 * Cherche un dossier.
 *
 * Aucune borne n'est appliquée ici : longueur minimale, plafond de résultats
 * et société sont imposés par Odoo. Les répéter donnerait l'illusion que le
 * navigateur y participe.
 */
export async function searchIntakes(
  options: IntakeSearchQuery,
  sessionId: string,
  correlationId: string,
): Promise<IntakeSearchPage> {
  const query: Record<string, string> = { q: options.q };
  if (options.limit !== undefined) query.limit = String(options.limit);
  return intakeSearchPage.parse(
    await opsGetQuery('intakes/search', query, sessionId, correlationId),
  );
}
