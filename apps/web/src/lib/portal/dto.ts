/**
 * Les contrats du portail — dérivés des projections Odoo, champ par champ.
 *
 * ## Ce que ces types n'ont pas
 *
 * Ils n'ont pas de fournisseur, pas de coût, pas de marge, pas de commission, pas
 * d'utilisateur interne, pas d'identifiant technique. Non parce qu'on évite de les
 * afficher : parce qu'ils **n'existent pas** dans le contrat.
 *
 * La différence est ce qui rend la règle tenable. Un type large dont l'UI
 * masquerait certains champs déplace la sécurité vers chaque composant, et il
 * suffit d'un `JSON.stringify` dans un état React, d'un log, ou d'un payload RSC
 * pour que le champ masqué parte quand même vers le navigateur. Un champ absent du
 * type ne peut être divulgué par aucun de ces chemins.
 *
 * ## Pourquoi valider à l'exécution
 *
 * `as PortalQuote` n'est pas une vérification, c'est une affirmation. Si Odoo
 * changeait une projection — un champ renommé, une clé disparue — le cast
 * continuerait de compiler et la page afficherait `undefined` là où le client
 * attend un montant. Zod fait échouer la frontière plutôt que l'affichage.
 *
 * Le schéma sert aussi de barrière dans l'autre sens : `.strict()` **refuse** une
 * clé inattendue au lieu de la retirer en silence. Si une future projection Odoo
 * ajoutait `margin` par erreur, la page ne s'afficherait pas — ce qui est
 * exactement le comportement voulu, et l'inverse de ce que fait un `.strip()`.
 */

import { z } from 'zod';

/** Chaîne facultative telle qu'Odoo la sérialise : la valeur ou `null`. */
const nullableText = z.string().nullable();

// ─── Devis ───────────────────────────────────────────────────────────

export const portalQuoteSchema = z
  .object({
    reference: z.string(),
    service: nullableText,
    status: z.string(),
    createdOn: nullableText,
    origin: nullableText,
    destination: nullableText,
    goodsDescription: nullableText,
    // `quantity` est un Char côté Odoo, pas un nombre : le client écrit
    // « 2 conteneurs 40' » aussi souvent qu'un chiffre.
    quantity: nullableText,
  })
  .strict();

export type PortalQuote = z.infer<typeof portalQuoteSchema>;
/** Le détail d'un devis n'expose rien de plus que sa ligne de liste. */
export type PortalQuoteDetail = PortalQuote;
export const portalQuoteDetailSchema = portalQuoteSchema;

// ─── Sourcing ────────────────────────────────────────────────────────

export const portalSourcingProposalSchema = z
  .object({
    reference: z.string(),
    status: z.string(),
    productName: nullableText,
    quantity: z.number(),
    unit: nullableText,
    // Le prix de vente et le total y sont : c'est ce qu'on demande au client
    // d'accepter. `cost_basis` et `margin` décrivent notre position, pas la
    // sienne — ils ne sont ni dans la projection, ni ici.
    unitPrice: z.number(),
    total: z.number(),
    currency: nullableText,
    validUntil: nullableText,
    estimatedDelivery: nullableText,
    commercialTerms: nullableText,
  })
  .strict();

export type PortalSourcingProposal = z.infer<typeof portalSourcingProposalSchema>;

export const portalSourcingRequestSchema = z
  .object({
    reference: z.string(),
    status: z.string(),
    productName: nullableText,
    productReference: nullableText,
    quantity: z.number(),
    unit: nullableText,
    createdOn: nullableText,
  })
  .strict();

export type PortalSourcingRequest = z.infer<typeof portalSourcingRequestSchema>;

/** Le détail ajoute les propositions **déjà envoyées** — jamais les brouillons. */
export const portalSourcingDetailSchema = portalSourcingRequestSchema
  .extend({ proposals: z.array(portalSourcingProposalSchema) })
  .strict();

export type PortalSourcingDetail = z.infer<typeof portalSourcingDetailSchema>;

// ─── Trading ─────────────────────────────────────────────────────────

export const portalTradeSchema = z
  .object({
    reference: z.string(),
    subject: z.string(),
    operationType: z.string(),
    operationTypeLabel: z.string(),
    status: z.string(),
    // Le volet VENTE uniquement. Une opération a deux contreparties ; le client
    // n'en est qu'une, et le volet achat ne le regarde pas.
    saleTotal: z.number(),
    currency: nullableText,
    origin: nullableText,
    destination: nullableText,
    expectedClose: nullableText,
    createdOn: nullableText,
  })
  .strict();

export type PortalTrade = z.infer<typeof portalTradeSchema>;
export type PortalTradeDetail = PortalTrade;
export const portalTradeDetailSchema = portalTradeSchema;

// ─── Expéditions ─────────────────────────────────────────────────────

export const portalShipmentEventSchema = z
  .object({
    date: nullableText,
    status: z.string(),
    statusLabel: z.string(),
    location: nullableText,
    description: nullableText,
  })
  .strict();

export type PortalShipmentEvent = z.infer<typeof portalShipmentEventSchema>;

export const portalShipmentPackageSchema = z
  .object({
    packageType: nullableText,
    description: nullableText,
    quantity: z.number(),
    totalWeightKg: z.number(),
    totalVolumeCbm: z.number(),
  })
  .strict();

export type PortalShipmentPackage = z.infer<typeof portalShipmentPackageSchema>;

export const portalShipmentSchema = z
  .object({
    reference: z.string(),
    transportMode: nullableText,
    transportModeLabel: nullableText,
    origin: nullableText,
    destination: nullableText,
    status: z.string(),
    statusLabel: z.string(),
    departureDate: nullableText,
    estimatedArrival: nullableText,
    actualArrival: nullableText,
    lastUpdate: nullableText,
    // Identifiants du client, imprimés sur ses documents : les lui donner lui
    // permet de suivre son envoi directement chez le transporteur.
    carrierTrackingNumber: nullableText,
    containerNumber: nullableText,
    goodsDescription: nullableText,
    packagesCount: z.number(),
    // Déjà filtrée sur `visible_to_customer` côté Odoo. Le frontend ne refiltre
    // pas : refiltrer laisserait croire que c'est lui la barrière.
    timeline: z.array(portalShipmentEventSchema),
  })
  .strict();

export type PortalShipment = z.infer<typeof portalShipmentSchema>;

export const portalShipmentDetailSchema = portalShipmentSchema
  .extend({ packages: z.array(portalShipmentPackageSchema) })
  .strict();

export type PortalShipmentDetail = z.infer<typeof portalShipmentDetailSchema>;

// ─── Documents ───────────────────────────────────────────────────────

export const portalDocumentSchema = z
  .object({
    // `DOC-<id>` : c'est la poignée publique du document. L'identifiant de la
    // pièce jointe Odoo, lui, n'apparaît nulle part — le connaître inviterait à
    // tenter `/web/content/<id>`, qui court-circuiterait le contrôle.
    reference: z.string(),
    name: z.string(),
    documentType: nullableText,
    documentTypeLabel: nullableText,
    relatedTo: z.string(),
    relatedReference: z.string(),
    publishedOn: nullableText,
  })
  .strict();

export type PortalDocument = z.infer<typeof portalDocumentSchema>;

// ─── Profil ──────────────────────────────────────────────────────────

export const portalProfileSchema = z
  .object({
    name: z.string(),
    email: nullableText,
    phone: nullableText,
    company: nullableText,
    city: nullableText,
    country: nullableText,
  })
  .strict();

export type PortalProfile = z.infer<typeof portalProfileSchema>;

// ─── Tableau de bord ─────────────────────────────────────────────────

export const portalDashboardSchema = z
  .object({
    counters: z
      .object({
        quotes: z.number(),
        sourcing: z.number(),
        trades: z.number(),
        shipments: z.number(),
        documents: z.number(),
      })
      .strict(),
    recent: z
      .object({
        quotes: z.array(portalQuoteSchema),
        sourcing: z.array(portalSourcingRequestSchema),
        trades: z.array(portalTradeSchema),
        shipments: z.array(portalShipmentSchema),
        documents: z.array(portalDocumentSchema),
      })
      .strict(),
  })
  .strict();

export type PortalDashboard = z.infer<typeof portalDashboardSchema>;

// ─── Enveloppe de liste ──────────────────────────────────────────────

/** `{ items, total, limit, offset }` — la pagination vient d'Odoo, bornée là-bas. */
export function portalListSchema<T extends z.ZodTypeAny>(item: T) {
  return z
    .object({
      items: z.array(item),
      total: z.number(),
      limit: z.number(),
      offset: z.number(),
    })
    .strict();
}

export interface PortalList<T> {
  readonly items: readonly T[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

/**
 * Champs qui ne doivent JAMAIS apparaître dans une réponse portail.
 *
 * Doublon assumé de ce que les `groups=` Odoo garantissent déjà. La raison : ici,
 * une violation devient visible immédiatement et par un test, alors qu'une
 * régression côté Odoo ne se manifesterait qu'en production, sur la page d'un
 * client, avec une marge affichée dessus.
 */
export const FORBIDDEN_KEYS = [
  'margin', 'marginRate', 'cost', 'costBasis', 'supplierCost', 'purchaseSubtotal',
  'commission', 'supplierId', 'supplierIds', 'supplierCount', 'supplier',
  'purchaseOrderIds', 'internalNotes', 'userId', 'responsibleId', 'teamId',
  'partnerId', 'customerId', 'attachmentId', 'priceValidated',
] as const;
