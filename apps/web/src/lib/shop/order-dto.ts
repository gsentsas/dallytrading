/** Contrats stricts des commandes boutique dans l'espace client. */

import { z } from 'zod';

import {
  deliveryFeeStateSchema,
  deliveryModeSchema,
  fulfillmentStateSchema,
  shopWorkflowStateSchema,
} from './checkout-schema';

export const shopOrderLineSchema = z
  .object({
    productName: z.string().min(1),
    quantity: z.number().positive(),
    unitPrice: z.number().nonnegative(),
    subtotal: z.number().nonnegative(),
  })
  .strict();
export type ShopOrderLine = z.infer<typeof shopOrderLineSchema>;

const deliveryStatusFields = {
  deliveryFeeStatus: deliveryFeeStateSchema.nullable(),
  deliveryFee: z.number().nonnegative().nullable(),
  grandTotal: z.number().nonnegative().nullable(),
  fulfillmentState: fulfillmentStateSchema,
  fulfillmentLabel: z.string().min(1),
};

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
    ...deliveryStatusFields,
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
    ...deliveryStatusFields,
    lines: z.array(shopOrderLineSchema),
    deliveryAddress: shopOrderAddressSchema.nullable(),
  })
  .strict();
export type ShopOrderDetail = z.infer<typeof shopOrderDetailSchema>;

export const shopOrderDetailEnvelopeSchema = z
  .object({ order: shopOrderDetailSchema })
  .strict();
