/**
 * Les encaissements Wave, côté serveur Next.
 *
 * ## Ce que le navigateur ne peut pas dire
 *
 * Ni le moyen de paiement, ni le bénéficiaire, ni le client, ni le dossier
 * autrement que par sa référence publique. Le contrat les exclut, et
 * `strict()` fait qu'une tentative échoue ici — avant tout appel réseau —
 * plutôt que d'être ignorée en silence.
 *
 * Le bénéficiaire descend malgré tout du serveur vers l'écran, en lecture :
 * l'opérateur doit voir sur quel compte l'argent arrive. Le lui faire lire
 * depuis Odoo évite qu'une interface annonce un nom et que le serveur en
 * crédite un autre.
 *
 * ## Aucune intégration Wave
 *
 * Ce module n'appelle pas Wave, n'écoute aucun webhook et ne conserve aucun
 * code. La référence Wave est un numéro que l'opérateur recopie depuis son
 * téléphone ; rien ici ne prétend le vérifier.
 */

import { z } from 'zod';

import { opsGet, opsPost } from '@/lib/auth/odoo-ops';

/** Le verdict comptable, en trois mots — jamais le message du moteur. */
const statutComptable = z.enum(['registered', 'pending', 'needs_review']);

export const encaissementLu = z
  .object({
    reference: z.string().min(1),
    amount: z.number(),
    currency_code: z.string(),
    paid_at: z.string(),
    payment_method: z.string(),
    beneficiary: z.string(),
    wave_reference: z.string(),
    note: z.string(),
    accounting_status: statutComptable,
  })
  .strict();

const listeEncaissements = z
  .object({
    items: z.array(encaissementLu),
    summary: z.array(
      z.object({ currency_code: z.string(), amount: z.number() }).strict(),
    ),
  })
  .strict();

export const contexteWave = z
  .object({
    intake_reference: z.string().min(1),
    customer_name: z.string(),
    /** Toujours « wave » à ce stade : c'est le serveur qui l'impose. */
    payment_method: z.literal('wave'),
    beneficiary: z.string().min(1),
    currencies: z.array(z.string().min(1)),
    payments: listeEncaissements,
  })
  .strict();

const listeDuDossier = listeEncaissements
  .extend({ intake_reference: z.string().min(1) })
  .strict();

/**
 * Ce que le navigateur a le droit de demander.
 *
 * Ni `payment_method`, ni `beneficiary`, ni `beneficiary_user_id`, ni
 * `partner_id` : ces valeurs sont décidées par le serveur, et les accepter
 * même avec la bonne valeur ferait croire au client qu'il les choisit.
 */
export const demandeWave = z
  .object({
    request_uuid: z.string().uuid(),
    amount: z.number().positive(),
    currency: z.string().trim().min(1).max(8),
    /** Facultative : un encaissement réel ne se refuse pas faute de numéro. */
    wave_reference: z.string().trim().max(64).nullable(),
    paid_at: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    note: z.string().trim().max(500),
  })
  .strict();

const resultatWave = z
  .object({
    status: z.enum(['created', 'replayed']),
    payment: encaissementLu,
  })
  .strict();

export type ContexteWave = z.infer<typeof contexteWave>;
export type EncaissementLu = z.infer<typeof encaissementLu>;
export type DemandeWave = z.infer<typeof demandeWave>;
export type ListeDuDossier = z.infer<typeof listeDuDossier>;

export async function fetchWaveContext(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<ContexteWave> {
  const brut = await opsGet<unknown>(
    `shipments/${reference}/wave-context`, sessionId, correlationId);
  return contexteWave.parse(brut);
}

export async function fetchShipmentPayments(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<ListeDuDossier> {
  const brut = await opsGet<unknown>(
    `shipments/${reference}/payments`, sessionId, correlationId);
  return listeDuDossier.parse(brut);
}

export async function recordWavePayment(
  reference: string,
  demande: DemandeWave,
  sessionId: string,
  correlationId: string,
): Promise<z.infer<typeof resultatWave>> {
  const brut = await opsPost<unknown>(
    `shipments/${reference}/payments`, demande, sessionId, correlationId);
  return resultatWave.parse(brut);
}
