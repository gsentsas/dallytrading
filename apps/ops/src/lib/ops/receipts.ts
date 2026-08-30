/**
 * Le reçu client, tel que le BFF le laisse passer.
 *
 * Le contrat est **strict** : une clé qu'Odoo ajouterait sans qu'on l'ait
 * voulue fait échouer la lecture au lieu d'atteindre l'écran. C'est la seule
 * protection mécanique contre le jour où un identifiant interne — un
 * `partner_id`, une clé de synchronisation — se retrouverait dans un document
 * que le client emporte.
 *
 * Rien n'est recalculé ici. Les montants arrivent déjà écrits, parce que le
 * papier et l'écran doivent afficher les mêmes caractères : deux formateurs
 * finiraient par diverger sur un arrondi, et c'est le client qui le
 * remarquerait.
 */

import { z } from 'zod';

import { opsGet, opsGetDocument } from '@/lib/auth/odoo-ops';
import { nomFichierRecu } from '@/lib/ops/recu-vocabulaire';

const texte = z.string();

const articleRecu = z
  .object({
    description: texte,
    goods_category: texte,
    quantity: z.number().int().nonnegative(),
    exact_weight_kg: z.number().nonnegative(),
    exact_weight_display: texte,
    billable_weight_kg: z.number().nonnegative(),
    dimensions: texte,
    customs_value_xof: z.number().nonnegative(),
    tariff_family: texte,
    // `null` dit « pas encore tarifé ». Jamais zéro : un client lirait
    // « rien à payer » là où le prix n'est pas décidé.
    applied_unit_price_eur: z.number().nullable(),
    transport_amount_eur: z.number().nullable(),
    applied_unit_price_display: texte,
    transport_amount_display: texte,
  })
  .strict();

const paiementRecu = z
  .object({
    date: texte,
    amount: z.number(),
    currency_code: texte,
    method: texte,
    collected_by: texte,
    wave_reference: texte,
    amount_display: texte,
  })
  .strict();

const encaisseParDevise = z
  .object({ currency_code: texte, amount: z.number(), display: texte })
  .strict();

const totauxRecu = z
  .object({
    articles_count: z.number().int().nonnegative(),
    weight_kg: z.number().nonnegative(),
    weight_display: texte,
    transport_amount_eur: z.number().nullable(),
    transport_amount_display: texte,
    currency_code: texte,
    paid: z.array(encaisseParDevise),
    // Un solde n'existe que lorsqu'il est exact ; sinon le motif dit pourquoi.
    balance_eur: z.number().nullable(),
    balance_display: texte,
    balance_reason: z.enum(['pricing_incomplete', 'currency_mismatch']).nullable(),
  })
  .strict();

export const recu = z
  .object({
    document: z
      .object({ title: texte, reference: texte, generated_at: texte })
      .strict(),
    company: z
      .object({ name: texte, phone: texte, email: texte, address: texte, vat: texte })
      .strict(),
    reference: texte.min(1),
    local_reference: texte,
    received_on: texte,
    state: texte,
    transport_mode: texte,
    transport_mode_label: texte,
    consolidation: z
      .object({ reference: texte, origin: texte, destination: texte })
      .strict(),
    customer: z
      .object({ name: texte, phone: texte, email: texte, address: texte })
      .strict(),
    articles: z.array(articleRecu),
    totals: totauxRecu,
    payments: z.array(paiementRecu),
    operator: z.object({ name: texte }).strict(),
    invoice_number: texte,
  })
  .strict();

export type Recu = z.infer<typeof recu>;

const reponseRecu = z.object({ receipt: recu }).strict();

export async function fetchReceipt(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<Recu> {
  const brut = await opsGet<unknown>(
    `intakes/${encodeURIComponent(reference)}/receipt`, sessionId, correlationId,
  );
  return reponseRecu.parse(brut).receipt;
}

/**
 * Le PDF, en octets.
 *
 * Le nom du fichier est reconstruit ici à partir de la seule référence du
 * dossier : celui d'Odoo n'est pas relayé, et aucun nom de client ne descend
 * dans la liste des téléchargements d'un téléphone qui passe de main en main.
 */
export async function fetchReceiptPdf(
  reference: string,
  sessionId: string,
  correlationId: string,
): Promise<{ readonly contenu: ArrayBuffer; readonly nomFichier: string }> {
  const document = await opsGetDocument(
    `intakes/${encodeURIComponent(reference)}/receipt/pdf`, sessionId, correlationId,
  );
  return { contenu: document.contenu, nomFichier: nomFichierRecu(reference) };
}

export { nomFichierRecu };
