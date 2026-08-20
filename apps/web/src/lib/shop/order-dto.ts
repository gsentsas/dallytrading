/**
 * Contrat des commandes boutique dans l'espace client.
 *
 * Les schémas sont stricts : une `sale.order` porte de nombreuses données
 * internes, et aucune ne doit atteindre la charge RSC simplement parce qu'un
 * module Odoo ajoute un champ.
 */

import { z } from 'zod';

import { deliveryModeSchema, shopWorkflowStateSchema } from './checkout-schema';

export const shopOrderLineSchema = z
  .object({
    productName: z.string().min(1),
    quantity: z.number().positive(),
    unitPrice: z.number().nonnegative(),
    subtotal: z.number().nonnegative(),
  })
  .strict();
export type ShopOrderLine = z.infer<typeof shopOrderLineSchema>;

export const shopOrderListItemSchema = z
  .object({
    reference: z.string().min(1),
    date: z.string().nullable(),
    stateLabel: z.string().min(1),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    deliveryMode: deliveryModeSchema.nullable(),
    deliveryModeLabel: z.string(),
    itemCount: z.number().int().nonnegative(),
  })
  .strict();
export type ShopOrderListItem = z.infer<typeof shopOrderListItemSchema>;

export const shopOrderListSchema = z
  .object({ orders: z.array(shopOrderListItemSchema) })
  .strict();
export type ShopOrderList = z.infer<typeof shopOrderListSchema>;

export const shopOrderAddressSchema = z
  .object({
    name: z.string().min(1),
    street: z.string().nullable(),
    city: z.string().nullable(),
    zip: z.string().nullable(),
    country: z.string().nullable(),
  })
  .strict();

/**
 * `state` est l'état métier public du workflow boutique, pas `sale.order.state`.
 * Le libellé reste la seule valeur affichée : il peut inclure le motif client
 * d'un refus ou d'une annulation, fourni par Odoo.
 */
export const shopOrderDetailSchema = z
  .object({
    reference: z.string().min(1),
    date: z.string().nullable(),
    state: shopWorkflowStateSchema,
    stateLabel: z.string().min(1),
    deliveryMode: deliveryModeSchema.nullable(),
    deliveryModeLabel: z.string(),
    currency: z.string().min(1),
    amountUntaxed: z.number().nonnegative(),
    amountTax: z.number().nonnegative(),
    amountTotal: z.number().nonnegative(),
    lines: z.array(shopOrderLineSchema),
    deliveryAddress: shopOrderAddressSchema,
  })
  .strict();
export type ShopOrderDetail = z.infer<typeof shopOrderDetailSchema>;

export const shopOrderDetailEnvelopeSchema = z
  .object({ order: shopOrderDetailSchema })
  .strict();
