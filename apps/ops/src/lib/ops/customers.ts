/**
 * La recherche client, côté serveur Next.
 *
 * ## Ce que ce module valide, et pourquoi
 *
 * En sortie, zod referme le contrat : un champ qu'Odoo ajouterait un jour au
 * DTO — un solde, un identifiant, une étiquette commerciale — resterait au
 * vestiaire au lieu d'atteindre le navigateur.
 *
 * En entrée, il refuse tout ce qui n'est pas exactement un critère. Ce n'est
 * pas une redite de la validation Odoo : c'est ce qui garantit qu'un champ
 * `name` glissé dans le corps ne franchit même pas le BFF, et donc que le
 * refus ne dépend pas d'une seule implémentation.
 */

import { z } from 'zod';

import { opsPost } from '@/lib/auth/odoo-ops';

/**
 * Ce que le navigateur a le droit de demander.
 *
 * `strict()` : une clé inconnue fait échouer la validation au lieu d'être
 * ignorée. Ignorer `{"name": "Mamadou"}` laisserait croire à l'appelant qu'il
 * a cherché par nom, alors qu'il aurait cherché sur rien.
 *
 * Il n'existe volontairement pas de critère « nom ». Le CRM tient déjà cette
 * règle pour les homonymes ; ici s'y ajoute qu'une recherche par nom est aussi
 * un moyen de feuilleter le fichier clients depuis un téléphone d'entrepôt.
 */
export const critereRecherche = z
  .union([
    z.object({ phone: z.string().trim().min(1).max(40) }).strict(),
    z.object({ email: z.string().trim().min(3).max(254) }).strict(),
  ]);

export type CritereRecherche = z.infer<typeof critereRecherche>;

const client = z
  .object({
    reference: z.string().uuid(),
    name: z.string(),
    phone: z.string(),
    email: z.string(),
    address: z.string(),
    customer_type: z.enum(['individual', 'business']),
  })
  .strict();

/**
 * Le résultat, dans ses trois formes.
 *
 * `ambiguous` ne porte aucun client, et le type l'impose : deux fiches veulent
 * dire qu'on ignore laquelle est devant le comptoir, et montrer la première
 * exposerait quelqu'un qui n'est pas là.
 */
const resultat = z.discriminatedUnion('status', [
  z.object({ status: z.literal('match'), customer: client }).strict(),
  z.object({ status: z.literal('not_found'), customer: z.null() }).strict(),
  z.object({ status: z.literal('ambiguous'), customer: z.null() }).strict(),
]);

export type Client = z.infer<typeof client>;
export type ResultatRecherche = z.infer<typeof resultat>;

/** Interroge Odoo, qui reste seul juge de ce qui est trouvé. */
export async function searchCustomer(
  critere: CritereRecherche,
  sessionId: string,
  correlationId: string,
): Promise<ResultatRecherche> {
  const brut = await opsPost<unknown>('customers/search', critere, sessionId, correlationId);
  return resultat.parse(brut);
}

/**
 * Ce que le navigateur a le droit de faire créer.
 *
 * `strict()` de nouveau, et cette fois l'enjeu est plus lourd qu'une recherche :
 * une clé acceptée ici deviendrait une colonne de `res.partner` écrite par le
 * navigateur. `is_company`, `company_id`, `partner_id` ne sont pas listés — ils
 * n'ont donc aucun chemin.
 *
 * `request_uuid` est obligatoire dès le contrat : c'est lui qui fait qu'une 4G
 * capricieuse ne crée pas deux fiches.
 */
export const demandeCreation = z
  .object({
    request_uuid: z.string().uuid(),
    customer_type: z.enum(['individual', 'business']),
    name: z.string().trim().min(1).max(200),
    phone: z.string().trim().min(1).max(40),
    email: z.string().trim().max(254).optional(),
    address: z.string().trim().min(1).max(500),
  })
  .strict();

export type DemandeCreation = z.infer<typeof demandeCreation>;

/**
 * Le résultat d'une création.
 *
 * « Existe déjà » est une issue normale, pas une erreur : le logisticien a un
 * client devant lui, et lui renvoyer un refus l'obligerait à recommencer une
 * recherche qu'il vient de faire.
 */
const resultatCreation = z.discriminatedUnion('status', [
  z.object({ status: z.literal('created'), customer: client }).strict(),
  z.object({ status: z.literal('existing'), customer: client }).strict(),
]);

export type ResultatCreation = z.infer<typeof resultatCreation>;

export async function createCustomer(
  demande: DemandeCreation,
  sessionId: string,
  correlationId: string,
): Promise<ResultatCreation> {
  const brut = await opsPost<unknown>('customers', demande, sessionId, correlationId);
  return resultatCreation.parse(brut);
}
