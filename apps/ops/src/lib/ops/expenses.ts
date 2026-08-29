/**
 * Les dépenses de terrain, côté serveur Next.
 *
 * Le contrat referme dans les deux sens. Une demande qui nommerait le payeur,
 * l'état ou le départ par son identifiant n'atteint pas Odoo : `strict()` la
 * rejette au lieu de laisser passer un champ ignoré. Une réponse qui porterait
 * un identifiant interne n'atteint pas le navigateur, pour la même raison.
 *
 * Le total n'est jamais converti. Une dépense en francs CFA et une dépense en
 * euros se lisent côte à côte, chacune dans sa devise : additionner les deux
 * demanderait un taux, et un taux inventé ici serait faux la moitié du temps.
 */

import { z } from 'zod';

import { opsGet, opsPost, opsPostFichier } from '@/lib/auth/odoo-ops';
import { MODES_PAIEMENT } from '@/lib/ops/expenses-vocabulaire';

export {
  LIBELLES_MODE,
  MODES_PAIEMENT,
  TAILLE_MAXIMALE_JUSTIFICATIF,
} from '@/lib/ops/expenses-vocabulaire';

/** Un départ, réduit à ce qui permet de le reconnaître sur le terrain. */
export const departDepense = z
  .object({
    reference: z.string().min(1),
    transport_mode: z.enum(['air', 'sea']),
    state: z.enum(['collecting', 'collection_closed', 'ready', 'departed', 'arrived']),
    origin: z.object({ city: z.string(), location: z.string() }).strict(),
    destination: z.object({ city: z.string(), location: z.string() }).strict(),
  })
  .strict();

const departs = z.object({ consolidations: z.array(departDepense) }).strict();

/**
 * Ce que le navigateur a le droit de demander.
 *
 * Ni `state`, ni `source`, ni `actor_name`, ni `consolidation_id` : ces
 * valeurs sont décidées par le serveur. `strict()` fait qu'une tentative
 * échoue ici, avant tout appel réseau, plutôt que d'être ignorée en silence.
 */
export const demandeDepense = z
  .object({
    request_uuid: z.string().uuid(),
    consolidation_reference: z.string().trim().min(1).max(120),
    expense_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    category: z.string().trim().min(1).max(200),
    description: z.string().trim().min(1).max(500),
    beneficiary: z.string().trim().max(200),
    amount: z.number().positive(),
    currency_code: z.string().trim().min(1).max(8),
    payment_method: z.enum(MODES_PAIEMENT),
    comment: z.string().trim().max(2000),
  })
  .strict();

export const depenseLue = z
  .object({
    reference: z.string().min(1),
    consolidation_reference: z.string(),
    expense_date: z.string(),
    category: z.string(),
    description: z.string(),
    beneficiary: z.string(),
    amount: z.number(),
    currency_code: z.string(),
    payment_method: z.string(),
    /** Le nom de l'acteur de caisse, pas celui du compte Odoo. */
    paid_by: z.string(),
    state: z.string(),
    has_receipt: z.boolean(),
    /**
     * Le terrain ne complète que ce que le terrain a saisi.
     *
     * Une dépense venue du tableur peut être rattachée au départ par le
     * back-office : elle compte dans le total et s'affiche, mais son
     * justificatif ne se joint pas d'ici. Le serveur le dit ; l'écran n'a pas
     * à le deviner.
     */
    can_attach_receipt: z.boolean(),
  })
  .strict();

const resultatDepense = z
  .object({
    status: z.enum(['created', 'replayed']),
    expense: depenseLue,
  })
  .strict();

const resultatJustificatif = z
  .object({
    status: z.enum(['attached', 'replayed']),
    expense: depenseLue,
  })
  .strict();

const listeDepenses = z
  .object({
    consolidation_reference: z.string(),
    expenses: z.array(depenseLue),
    summary: z.array(
      z.object({ currency_code: z.string(), amount: z.number() }).strict(),
    ),
  })
  .strict();

export type DepartDepense = z.infer<typeof departDepense>;
export type DemandeDepense = z.infer<typeof demandeDepense>;
export type DepenseLue = z.infer<typeof depenseLue>;
export type ListeDepenses = z.infer<typeof listeDepenses>;

export async function fetchExpenseConsolidations(
  sessionId: string,
  correlationId: string,
): Promise<DepartDepense[]> {
  const brut = await opsGet<unknown>('expense-consolidations', sessionId, correlationId);
  return departs.parse(brut).consolidations;
}

export async function fetchExpenses(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<ListeDepenses> {
  const brut = await opsGet<unknown>(
    `consolidations/${reference}/expenses`, sessionId, correlationId);
  return listeDepenses.parse(brut);
}

export async function recordExpense(
  demande: DemandeDepense,
  sessionId: string,
  correlationId: string,
): Promise<z.infer<typeof resultatDepense>> {
  const brut = await opsPost<unknown>('expenses', demande, sessionId, correlationId);
  return resultatDepense.parse(brut);
}

/**
 * Joint la photo du justificatif.
 *
 * Deuxième geste, jamais fondu dans le premier : la dépense existe déjà quand
 * cet appel part. Un échec ici — réseau coupé, photo trop lourde, fichier
 * illisible — laisse l'argent enregistré et se reprend plus tard.
 */
export async function attachReceipt(
  reference: string,
  requestUuid: string,
  fichier: { readonly nom: string; readonly type: string; readonly contenu: Blob },
  sessionId: string,
  correlationId: string,
): Promise<z.infer<typeof resultatJustificatif>> {
  const brut = await opsPostFichier<unknown>(
    `expenses/${reference}/receipt`,
    fichier,
    { request_uuid: requestUuid },
    sessionId,
    correlationId,
  );
  return resultatJustificatif.parse(brut);
}
