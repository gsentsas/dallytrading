/**
 * Contrats stricts du checkout E-commerce Pro.
 *
 * Le navigateur ne fournit ni prix, ni identifiant de panier, ni lignes : le BFF
 * les reconstruit depuis le cookie scellé. Au Lot C, il choisit seulement le code
 * public d'une méthode de remise et, si cette méthode livre, une adresse. Les
 * frais reviennent d'Odoo dans la projection de commande ; aucun montant n'est
 * accepté dans la requête.
 */

import { z } from 'zod';

import {
  deliveryMethodCodeSchema,
  shippingAddressSchema,
} from './delivery';

export const deliveryModeSchema = deliveryMethodCodeSchema;
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
    shipping: shippingAddressSchema.optional(),
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

/** État public du workflow commercial, séparé de `sale.order.state`. */
export const shopWorkflowStateSchema = z.enum([
  'received',
  'validated',
  'rejected',
  'cancelled',
]);
export type ShopWorkflowState = z.infer<typeof shopWorkflowStateSchema>;

export const deliveryFeeStateSchema = z.enum([
  'free',
  'fixed',
  'pending_quote',
  'quoted',
]);

export const fulfillmentStateSchema = z.enum([
  'pending',
  'preparing',
  'ready',
  'out_for_delivery',
  'delivered',
  'picked_up',
]);

const orderDeliveryMethodSchema = z
  .object({
    code: deliveryMethodCodeSchema,
    name: z.string().min(1).max(128),
    kind: z.enum(['pickup', 'delivery']),
    requiresAddress: z.boolean(),
  })
  .strict();

const publicShippingAddressSchema = z
  .object({
    name: z.string().max(128),
    phone: z.string().max(32),
    street: z.string().max(200),
    street2: z.string().max(200),
    city: z.string().max(100),
    zip: z.string().max(20),
    countryCode: z.string().regex(/^$|^[A-Z]{2}$/),
  })
  .strict();

export const orderDeliverySchema = z
  .object({
    method: orderDeliveryMethodSchema,
    fee: z
      .object({
        status: deliveryFeeStateSchema,
        amount: z.number().nonnegative().nullable(),
        currency: z.string().min(1).max(8),
      })
      .strict(),
    shippingAddress: publicShippingAddressSchema.nullable(),
    fulfillment: z
      .object({
        state: fulfillmentStateSchema,
        label: z.string().min(1).max(128),
      })
      .strict(),
  })
  .strict();

export const shopOrderSchema = z
  .object({
    reference: z.string().min(1),
    status: shopWorkflowStateSchema,
    deliveryMode: deliveryModeSchema,
    deliveryModeLabel: z.string().min(1),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    delivery: orderDeliverySchema,
    grandTotal: z.number().nonnegative().nullable(),
    lines: z.array(orderLineSchema),
    replayed: z.boolean(),
  })
  .strict();
export type ShopOrder = z.infer<typeof shopOrderSchema>;
