/**
 * Le dossier et ses articles, côté serveur Next.
 *
 * Ce module ne décide de rien : les règles de modification, les totaux et la
 * tarification appartiennent à Odoo. Il refuse simplement ce qu'il ne
 * reconnaît pas, dans les deux sens — une demande hors contrat n'atteint pas
 * le serveur, une réponse hors contrat n'atteint pas le navigateur.
 */

import { z } from 'zod';

import { opsGet, opsPost, opsPut } from '@/lib/auth/odoo-ops';
import { paiementLu } from '@/lib/ops/payments';

const dimension = z.number().positive().nullable();

/** Un article, tel que le comptoir le saisit. Identique à l'étape 7. */
export const saisieLigne = z
  .object({
    line_uuid: z.string().uuid(),
    package_type: z.enum(['parcel', 'pallet', 'crate', 'bag', 'drum', 'other']),
    goods_category: z.string().trim().min(1).max(200),
    description: z.string().trim().min(1).max(500),
    quantity: z.number().int().positive(),
    announced_weight_kg: z.number().nonnegative().nullable(),
    exact_weight_kg: z.number().positive(),
    length_cm: dimension,
    width_cm: dimension,
    height_cm: dimension,
    billing_method: z.enum(['real', 'volumetric', 'quote']),
    tariff_family_code: z.string().trim().min(1).max(80),
    customs_value_xof: z.number().positive(),
  })
  .strict()
  .refine((ligne) => {
    // Toutes les dimensions, ou aucune : une seule ne calcule aucun volume.
    const fournies = [ligne.length_cm, ligne.width_cm, ligne.height_cm]
      .filter((valeur) => valeur !== null);
    if (fournies.length !== 0 && fournies.length !== 3) return false;
    return ligne.billing_method !== 'volumetric' || fournies.length === 3;
  }, 'Dimensions incomplètes.');

export const demandeAjout = z
  .object({ request_uuid: z.string().uuid(), line: saisieLigne })
  .strict();

export const demandeCorrection = z
  .object({
    request_uuid: z.string().uuid(),
    expected_revision: z.string().min(1),
    line: saisieLigne,
  })
  .strict();

const ligneLue = z
  .object({
    reference: z.string().uuid(),
    revision: z.string().min(1),
    description: z.string(),
    goods_category: z.string(),
    package_type: z.string(),
    quantity: z.number().int().positive(),
    announced_weight_kg: z.number().nullable(),
    exact_weight_kg: z.number(),
    length_cm: z.number().nullable(),
    width_cm: z.number().nullable(),
    height_cm: z.number().nullable(),
    volume_cbm: z.number(),
    billing_method: z.enum(['real', 'volumetric', 'quote']),
    tariff_family_code: z.string(),
    customs_value_xof: z.number(),
    pricing_status: z.enum(['automatic', 'manual_required', 'quote', 'manual']),
    billable_weight_kg: z.number(),
    applied_unit_price_eur: z.number().nullable(),
    transport_amount_eur: z.number().nullable(),
  })
  .strict();

const dossier = z
  .object({
    reference: z.string().min(1),
    local_reference: z.string().regex(/^A\d{3,}$/),
    consolidation_reference: z.string().min(1),
    state: z.string(),
    received_on: z.string().nullable(),
    // Le nom seul : ni téléphone, ni adresse, ni identifiant.
    customer: z.object({ name: z.string() }).strict(),
    editable: z.boolean(),
    edit_block_reason: z
      .enum(['billing_locked', 'consolidation_not_open', 'intake_not_editable'])
      .nullable(),
    lines: z.array(ligneLue),
    totals: z
      .object({
        lines_count: z.number().int().nonnegative(),
        weight_kg: z.number(),
        volume_cbm: z.number(),
        // `null` tant qu'une ligne n'est pas tarifée : un total partiel
        // affiché comme un prix serait un mensonge.
        transport_amount_eur: z.number().nullable(),
        pricing_complete: z.boolean(),
      })
      .strict(),
    payments: z.array(paiementLu),
    // Un total par devise. Additionner des euros et des francs demanderait un
    // taux, et un taux choisi ici serait faux la moitié du temps.
    payment_summary: z.array(
      z.object({ currency_code: z.string(), amount: z.number() }).strict(),
    ),
  })
  .strict();

const detail = z.object({ intake: dossier }).strict();
const mutation = z
  .object({
    status: z.enum(['added', 'updated']),
    intake: dossier,
    line: ligneLue,
  })
  .strict();

export type LigneLue = z.infer<typeof ligneLue>;
export type Dossier = z.infer<typeof dossier>;
export type SaisieLigne = z.infer<typeof saisieLigne>;
export type Mutation = z.infer<typeof mutation>;

export async function fetchIntake(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<Dossier> {
  const brut = await opsGet<unknown>(
    `intakes/${reference}`, sessionId, correlationId);
  return detail.parse(brut).intake;
}

export async function addLine(
  reference: string,
  demande: z.infer<typeof demandeAjout>,
  sessionId: string,
  correlationId: string,
): Promise<Mutation> {
  const brut = await opsPost<unknown>(
    `intakes/${reference}/lines`, demande, sessionId, correlationId);
  return mutation.parse(brut);
}

export async function updateLine(
  reference: string,
  lineUuid: string,
  demande: z.infer<typeof demandeCorrection>,
  sessionId: string,
  correlationId: string,
): Promise<Mutation> {
  const brut = await opsPut<unknown>(
    `intakes/${reference}/lines/${lineUuid}`, demande, sessionId, correlationId);
  return mutation.parse(brut);
}
