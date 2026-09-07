/**
 * Les deux lectures de supervision : ce qui cloche, et ce que le tableur a reçu.
 *
 * Ce module ne calcule rien. Les anomalies sont établies par Odoo, qui seul
 * sait ce qu'une facture couvre et ce qu'un départ exige ; les compteurs de
 * projection viennent de l'outbox. Les recalculer ici en ferait une seconde
 * version, qui divergerait le jour où une règle métier bouge.
 *
 * Les schémas sont stricts dans les deux sens : une réponse qui porterait une
 * clé inattendue — un identifiant Odoo, un `last_error` — n'atteint pas le
 * navigateur.
 */

import { z } from 'zod';

import { opsGet } from '@/lib/auth/odoo-ops';

/** Les six natures d'anomalie. Vocabulaire fermé, comme côté serveur. */
export const typeAnomalie = z.enum([
  'SHEET_PROJECTION_FAILED',
  'SHEET_PROJECTION_RETRY',
  'UNBILLED_PACKAGE',
  'MISSING_TARIFF',
  'PAYMENT_REVIEW_REQUIRED',
  'INCOMPLETE_BEFORE_DEPARTURE',
]);

const anomalie = z
  .object({
    type: typeAnomalie,
    /** La référence métier du dossier ou du départ. Jamais une clé primaire. */
    reference: z.string(),
    title: z.string().min(1),
    /** Une phrase rédigée pour l'opérateur. Jamais un message de transport. */
    operator_message: z.string().min(1),
    severity: z.enum(['high', 'medium', 'low']),
    /** `null` quand il n'y a rien à ouvrir — un incident de transport, par exemple. */
    action: z.enum(['open_intake']).nullable(),
    intake_reference: z.string().nullable(),
  })
  .strict();

const listeAnomalies = z
  .object({
    anomalies: z.array(anomalie),
    total: z.number().int().nonnegative(),
    /** Vrai quand la liste dépasse le plafond du serveur. */
    truncated: z.boolean(),
  })
  .strict();

/**
 * L'état du transport Odoo → tableur.
 *
 * Distinct de la file de l'appareil, qui vit dans IndexedDB. Les additionner
 * produirait un nombre qui ne veut rien dire : ce sont deux systèmes, deux
 * pannes, deux remèdes.
 */
const etatProjection = z
  .object({
    counts: z
      .object({
        pending: z.number().int().nonnegative(),
        retry: z.number().int().nonnegative(),
        failed: z.number().int().nonnegative(),
        synced: z.number().int().nonnegative(),
      })
      .strict(),
    operator_message: z.string().min(1),
    last_synced_at: z.string().nullable(),
  })
  .strict();

export type Anomalie = z.infer<typeof anomalie>;
export type ListeAnomalies = z.infer<typeof listeAnomalies>;
export type EtatProjection = z.infer<typeof etatProjection>;

export async function fetchAnomalies(
  sessionId: string,
  correlationId: string,
): Promise<ListeAnomalies> {
  const brut = await opsGet<unknown>('anomalies', sessionId, correlationId);
  return listeAnomalies.parse(brut);
}

export async function fetchEtatProjection(
  sessionId: string,
  correlationId: string,
): Promise<EtatProjection> {
  const brut = await opsGet<unknown>('sheet-sync', sessionId, correlationId);
  return etatProjection.parse(brut);
}
