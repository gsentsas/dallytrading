/**
 * Le contrat du formulaire de commande, et la commande rendue.
 *
 * Le navigateur n'envoie ni prix, ni identifiant de panier, ni identifiant de
 * client, ni lignes. Les lignes et l'identifiant vivent dans le cookie scellé et
 * le BFF les lit côté serveur. Tous les schémas restent stricts : une clé inconnue
 * est une erreur, jamais une donnée silencieusement ignorée.
 */

import { z } from 'zod';

export const deliveryModeSchema = z.enum(['pickup', 'delivery_to_confirm']);
export type DeliveryMode = z.infer<typeof deliveryModeSchema>;

const texte = (max: number) =>
  z
    .string()
    .transform((valeur) => valeur.trim())
    .refine((valeur) => valeur.length > 0, { message: 'Ce champ est requis.' })
    .refine((valeur) => valeur.length <= max, {
      message: `Ce champ ne peut pas dépasser ${max} caractères.`,
    });

const texteFacultatif = (max: number) =>
  z
    .string()
    .transform((valeur) => valeur.trim())
    .refine((valeur) => valeur.length <= max, {
      message: `Ce champ ne peut pas dépasser ${max} caractères.`,
    })
    .transform((valeur) => (valeur.length === 0 ? undefined : valeur))
    .optional();

const EMAIL = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]{2,}$/;

export const guestCustomerSchema = z
  .object({
    name: texte(128),
    email: texte(254).refine((valeur) => EMAIL.test(valeur), {
      message: 'Merci d’indiquer une adresse e-mail valide.',
    }),
    phone: texteFacultatif(32),
    street: texteFacultatif(200),
    city: texteFacultatif(100),
    zip: texteFacultatif(20),
    country_code: z
      .string()
      .trim()
      .toUpperCase()
      .refine((valeur) => valeur === '' || /^[A-Z]{2}$/.test(valeur), {
        message: 'Le code pays doit comporter deux lettres.',
      })
      .transform((valeur) => (valeur === '' ? undefined : valeur))
      .optional(),
  })
  .strict();
export type GuestCustomer = z.infer<typeof guestCustomerSchema>;

export const checkoutRequestSchema = z
  .object({
    deliveryMode: deliveryModeSchema,
    customer: guestCustomerSchema.optional(),
  })
  .strict();
export type CheckoutRequest = z.infer<typeof checkoutRequestSchema>;

export const orderLineSchema = z
  .object({
    reference: z.string().min(1),
    name: z.string().min(1),
    quantity: z.number().positive(),
    unitPrice: z.number().nonnegative(),
    subtotal: z.number().nonnegative(),
  })
  .strict();

/**
 * État public du workflow boutique.
 *
 * Il est séparé de `sale.order.state`. Une commande peut être `validated` ici
 * tout en restant `draft` dans Vente : le Lot B n'a pas le droit de déclencher
 * picking, facture ou paiement.
 */
export const shopWorkflowStateSchema = z.enum([
  'received',
  'validated',
  'rejected',
  'cancelled',
]);
export type ShopWorkflowState = z.infer<typeof shopWorkflowStateSchema>;

export const shopOrderSchema = z
  .object({
    reference: z.string().min(1),
    status: shopWorkflowStateSchema,
    deliveryMode: deliveryModeSchema,
    deliveryModeLabel: z.string(),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    lines: z.array(orderLineSchema),
    replayed: z.boolean(),
  })
  .strict();
export type ShopOrder = z.infer<typeof shopOrderSchema>;
