/**
 * Le contrat de la fiche en lecture seule d'un dossier repris.
 *
 * ## Pourquoi un contrat séparé de celui de la fiche native
 *
 * La fiche native porte la tarification, les transitions permises et la
 * révision de chaque article — tout ce qui sert à écrire. Hériter de son
 * schéma pour en retrancher ensuite les champs gênants ferait dépendre la
 * confidentialité d'une soustraction, et une soustraction s'oublie. Celui-ci
 * énumère, et `.strict()` fait tomber la lecture si un champ de plus descend.
 *
 * ## Ce que `reference` désigne
 *
 * La référence **globale**, seule clé de navigation. `local_reference`
 * s'affiche, elle ne compose jamais d'URL : `A001` est local à son départ.
 */

import { z } from 'zod';

import { opsGet } from '@/lib/auth/odoo-ops';

const ligneLegacy = z.object({
  description: z.string(),
  goods_category: z.string(),
  package_type: z.string(),
  quantity: z.number(),
  announced_weight_kg: z.number().nullable(),
  exact_weight_kg: z.number(),
  length_cm: z.number().nullable(),
  width_cm: z.number().nullable(),
  height_cm: z.number().nullable(),
  volume_cbm: z.number(),
}).strict();

/**
 * L'encaissement, sans sa référence.
 *
 * Côté serveur, la référence publique d'un paiement non `ops:` est la clé
 * externe telle quelle. C'est une identité technique ; elle ne dit rien au
 * logisticien, et `.strict()` garantit qu'elle ne réapparaîtra pas un jour
 * sans décision.
 */
const paiementLegacy = z.object({
  amount: z.number(),
  currency_code: z.string(),
  payment_date: z.string(),
  payment_method: z.object({
    code: z.string(),
    name: z.string(),
  }).strict(),
  collector: z.string(),
  accounting_status: z.string(),
}).strict();

export const ficheLegacy = z.object({
  /** Déclaré par le serveur, jamais déduit d'une absence de bouton. */
  readonly: z.literal(true),
  reference: z.string().min(1),
  local_reference: z.string(),
  state: z.string(),
  state_label: z.string(),
  transport_mode: z.string(),
  direction: z.string(),
  consolidation_reference: z.string(),
  received_on: z.string(),
  customer: z.object({
    name: z.string(),
    phone: z.string(),
  }).strict(),
  lines: z.array(ligneLegacy),
  totals: z.object({
    lines_count: z.number(),
    weight_kg: z.number(),
    volume_cbm: z.number(),
  }).strict(),
  payments: z.array(paiementLegacy),
  payment_summary: z.array(z.object({
    currency_code: z.string(),
    amount: z.number(),
  }).strict()),
}).strict();

const reponseLegacy = z.object({ intake: ficheLegacy }).strict();

export type FicheLegacy = z.infer<typeof ficheLegacy>;
export type LigneLegacy = z.infer<typeof ligneLegacy>;
export type PaiementLegacy = z.infer<typeof paiementLegacy>;

export const LONGUEUR_REFERENCE_MAXIMALE = 120;

/**
 * La forme d'une référence globale, mesurée sur les données réelles.
 *
 * Les 52 références de production n'emploient que des lettres, des chiffres,
 * le tiret et le souligné — cinq d'entre elles portent un souligné, par
 * exemple `SN-DK_FR-PA_004`. Une classe qui l'oublierait rendrait ces
 * dossiers-là inatteignables sans qu'aucun test ne s'en aperçoive.
 *
 * La barre verticale n'y figure pas : elle n'apparaît que dans les clés de
 * ligne des colis, qui ne quittent jamais le serveur.
 */
const FORME_REFERENCE = /^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$/;

/**
 * La référence, ou rien.
 *
 * Une seule fonction pour la route et pour l'appel, afin qu'un refus ait
 * toujours le même sens. Elle ne décode pas : le routeur d'App Router livre
 * déjà le segment décodé, et redécoder transformerait `A%252DB` en `A-B` —
 * mesuré, et corrigé ici.
 */
export function normaliserReference(brute: unknown): string | null {
  if (typeof brute !== 'string') return null;
  const reference = brute.trim();
  if (!reference || reference.length > LONGUEUR_REFERENCE_MAXIMALE) return null;
  return FORME_REFERENCE.test(reference) ? reference : null;
}

function ressource(reference: string): string {
  const propre = normaliserReference(reference);
  if (propre === null) throw new Error('Référence de dossier invalide.');
  return `intakes/${propre}/legacy-detail`;
}

/** Lit la fiche. Aucune écriture n'existe sur ce chemin. */
export async function fetchLegacyIntake(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<FicheLegacy> {
  return reponseLegacy.parse(
    await opsGet(ressource(reference), sessionId, correlationId),
  ).intake;
}
