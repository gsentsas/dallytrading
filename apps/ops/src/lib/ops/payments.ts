/**
 * Les encaissements, côté serveur Next.
 *
 * Le contrat referme dans les deux sens : une demande qui nommerait le
 * collecteur ou la source n'atteint pas le serveur, et une réponse qui
 * porterait un identifiant comptable ou un message de journal n'atteint pas le
 * navigateur.
 */

import { z } from 'zod';

import { opsGet, opsPost } from '@/lib/auth/odoo-ops';

/** Un canal, réduit à ce qui se choisit au comptoir. */
export const canalPaiement = z
  .object({
    code: z.string().min(1),
    name: z.string().min(1),
    currency_code: z.string().min(1),
  })
  .strict();

const canaux = z.object({ channels: z.array(canalPaiement) }).strict();

/**
 * Ce que le navigateur a le droit de demander.
 *
 * Ni `collected_by`, ni `source`, ni `external_payment_key` : ces valeurs sont
 * décidées par le serveur, et `strict()` fait qu'une tentative échoue au lieu
 * d'être silencieusement ignorée.
 */
export const demandePaiement = z
  .object({
    request_uuid: z.string().uuid(),
    amount: z.number().positive(),
    payment_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    payment_method: z.string().trim().min(1).max(40),
    currency_code: z.string().trim().min(1).max(8),
  })
  .strict();

export const paiementLu = z
  .object({
    reference: z.string().min(1),
    amount: z.number(),
    currency_code: z.string(),
    payment_date: z.string(),
    payment_method: z.object({ code: z.string(), name: z.string() }).strict(),
    collector: z.string(),
    // Trois mots, jamais l'état brut du moteur ni son message d'erreur.
    accounting_status: z.enum(['registered', 'pending', 'needs_review']),
  })
  .strict();

const resultatPaiement = z
  .object({
    status: z.enum(['created', 'replayed']),
    payment: paiementLu,
  })
  .strict();

export type CanalPaiement = z.infer<typeof canalPaiement>;
export type PaiementLu = z.infer<typeof paiementLu>;
export type DemandePaiement = z.infer<typeof demandePaiement>;

export async function fetchPaymentChannels(
  sessionId: string,
  correlationId: string,
): Promise<CanalPaiement[]> {
  const brut = await opsGet<unknown>('payment-channels', sessionId, correlationId);
  return canaux.parse(brut).channels;
}

export async function recordPayment(
  reference: string,
  demande: DemandePaiement,
  sessionId: string,
  correlationId: string,
): Promise<z.infer<typeof resultatPaiement>> {
  const brut = await opsPost<unknown>(
    `intakes/${reference}/payments`, demande, sessionId, correlationId);
  return resultatPaiement.parse(brut);
}
